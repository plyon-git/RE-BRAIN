use brain_resolver::{resolve_batch, ResolveRequest, IDENTITY_CONTRACT_VERSION};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const MAX_HEADER_BYTES: usize = 16 * 1024;
const MAX_BODY_BYTES: usize = 2 * 1024 * 1024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
const WORKERS: usize = 4;
const QUEUE_CAPACITY: usize = 128;

struct Request {
    method: String,
    path: String,
    headers: HashMap<String, String>,
    body: Vec<u8>,
}

struct HttpError {
    status: u16,
    code: &'static str,
    message: &'static str,
}

fn error(status: u16, code: &'static str, message: &'static str) -> HttpError {
    HttpError { status, code, message }
}

fn read_chunk(stream: &mut TcpStream, buffer: &mut [u8], started: Instant) -> Result<usize, HttpError> {
    let remaining = REQUEST_TIMEOUT.checked_sub(started.elapsed())
        .ok_or_else(|| error(408, "request_timeout", "request read deadline exceeded"))?;
    stream.set_read_timeout(Some(remaining)).map_err(|_| error(400, "read_error", "unable to read request"))?;
    match stream.read(buffer) {
        Ok(size) => Ok(size),
        Err(e) if matches!(e.kind(), std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock) =>
            Err(error(408, "request_timeout", "request read deadline exceeded")),
        Err(_) => Err(error(400, "read_error", "unable to read request")),
    }
}

/// Only bounded Content-Length requests are accepted. Connections always close.
fn read_request(stream: &mut TcpStream) -> Result<Request, HttpError> {
    let started = Instant::now();
    let mut received = Vec::with_capacity(4096);
    let mut chunk = [0_u8; 4096];
    let header_end = loop {
        let count = read_chunk(stream, &mut chunk, started)?;
        if count == 0 { return Err(error(400, "incomplete_request", "incomplete HTTP headers")); }
        received.extend_from_slice(&chunk[..count]);
        if let Some(index) = received.windows(4).position(|w| w == b"\r\n\r\n") {
            if index + 4 > MAX_HEADER_BYTES { return Err(error(431, "headers_too_large", "HTTP headers exceed 16 KiB")); }
            break index + 4;
        }
        if received.len() >= MAX_HEADER_BYTES { return Err(error(431, "headers_too_large", "HTTP headers exceed 16 KiB")); }
    };
    let header = std::str::from_utf8(&received[..header_end - 4])
        .map_err(|_| error(400, "invalid_headers", "HTTP headers must be valid UTF-8"))?;
    let mut lines = header.split("\r\n");
    let request_line: Vec<_> = lines.next().unwrap_or("").split_whitespace().collect();
    if request_line.len() != 3 || !matches!(request_line[2], "HTTP/1.0" | "HTTP/1.1") {
        return Err(error(400, "invalid_request_line", "invalid HTTP request line"));
    }
    let method = request_line[0].to_owned();
    let path = request_line[1].split('?').next().unwrap_or("").to_owned();
    let mut headers = HashMap::new();
    for line in lines {
        let (name, value) = line.split_once(':').ok_or_else(|| error(400, "invalid_headers", "invalid HTTP header"))?;
        if name.is_empty() || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-') {
            return Err(error(400, "invalid_headers", "invalid HTTP header name"));
        }
        let name = name.to_ascii_lowercase();
        if headers.insert(name, value.trim().to_owned()).is_some() {
            return Err(error(400, "duplicate_header", "duplicate HTTP headers are not accepted"));
        }
    }
    if headers.contains_key("transfer-encoding") {
        return Err(error(400, "unsupported_transfer_encoding", "use Content-Length instead of Transfer-Encoding"));
    }
    let content_length = match headers.get("content-length") {
        Some(value) if !value.is_empty() && value.bytes().all(|c| c.is_ascii_digit()) =>
            value.parse::<usize>().map_err(|_| error(413, "payload_too_large", "request body exceeds 2 MiB"))?,
        Some(_) => return Err(error(400, "invalid_content_length", "invalid Content-Length")),
        None if method == "POST" => return Err(error(411, "length_required", "POST requires Content-Length")),
        None => 0,
    };
    if content_length > MAX_BODY_BYTES { return Err(error(413, "payload_too_large", "request body exceeds 2 MiB")); }
    let mut body = received[header_end..].to_vec();
    if body.len() > content_length { body.truncate(content_length); }
    while body.len() < content_length {
        let remaining = content_length - body.len();
        let chunk_size = remaining.min(chunk.len());
        let count = read_chunk(stream, &mut chunk[..chunk_size], started)?;
        if count == 0 { return Err(error(400, "incomplete_request", "incomplete HTTP request body")); }
        body.extend_from_slice(&chunk[..count]);
    }
    Ok(Request { method, path, headers, body })
}

fn write_response(stream: &mut TcpStream, status: u16, body: &Value) {
    let reason = match status {
        200 => "OK", 400 => "Bad Request", 401 => "Unauthorized", 404 => "Not Found",
        405 => "Method Not Allowed", 408 => "Request Timeout", 411 => "Length Required",
        413 => "Payload Too Large", 431 => "Request Header Fields Too Large",
        503 => "Service Unavailable", _ => "Internal Server Error",
    };
    let bytes = serde_json::to_vec(body).unwrap_or_else(|_| b"{\"error\":{\"code\":\"serialization_error\"}}".to_vec());
    let header = format!("HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\nCache-Control: no-store\r\n\r\n", bytes.len());
    let _ = stream.set_write_timeout(Some(REQUEST_TIMEOUT));
    let _ = stream.write_all(header.as_bytes());
    let _ = stream.write_all(&bytes);
}

fn constant_time_equal(a: &[u8], b: &[u8]) -> bool {
    let mut difference = a.len() ^ b.len();
    for index in 0..a.len().max(b.len()) {
        difference |= usize::from(a.get(index).copied().unwrap_or(0) ^ b.get(index).copied().unwrap_or(0));
    }
    difference == 0
}

fn authorized(request: &Request, api_key: &Option<String>) -> bool {
    match api_key {
        None => true,
        Some(expected) => {
            let bearer = request.headers.get("authorization").and_then(|v| v.strip_prefix("Bearer "));
            let direct = request.headers.get("x-api-key").map(String::as_str);
            bearer.or(direct).map(|supplied| constant_time_equal(supplied.as_bytes(), expected.as_bytes())).unwrap_or(false)
        }
    }
}

fn serve(mut stream: TcpStream, api_key: &Option<String>) {
    let request = match read_request(&mut stream) {
        Ok(value) => value,
        Err(e) => { write_response(&mut stream, e.status, &json!({"error": {"code": e.code, "message": e.message}})); return; }
    };
    if request.path == "/health" && request.method == "GET" {
        write_response(&mut stream, 200, &json!({"status":"ok", "service":"brain-resolver", "identity_contract_version":IDENTITY_CONTRACT_VERSION}));
        return;
    }
    if request.path != "/resolve" {
        write_response(&mut stream, 404, &json!({"error":{"code":"not_found", "message":"endpoint not found"}}));
        return;
    }
    if request.method != "POST" {
        write_response(&mut stream, 405, &json!({"error":{"code":"method_not_allowed", "message":"use POST /resolve"}}));
        return;
    }
    if !authorized(&request, api_key) {
        write_response(&mut stream, 401, &json!({"error":{"code":"unauthorized", "message":"a valid API key is required"}}));
        return;
    }
    let request: ResolveRequest = match serde_json::from_slice(&request.body) {
        Ok(value) => value,
        Err(_) => { write_response(&mut stream, 400, &json!({"error":{"code":"invalid_json", "message":"expected JSON with a records array and string identity fields"}})); return; }
    };
    match resolve_batch(&request) {
        Ok(response) => write_response(&mut stream, 200, &serde_json::to_value(response).unwrap()),
        Err(e) => write_response(&mut stream, 400, &json!({"error":e})),
    }
}

fn port() -> Result<u16, String> {
    let raw = env::var("BRAIN_RESOLVER_PORT").or_else(|_| env::var("PORT")).unwrap_or_else(|_| "8082".to_owned());
    let value = raw.parse::<u16>().map_err(|_| "resolver port must be an integer between 1 and 65535".to_owned())?;
    if value == 0 { return Err("resolver port must be between 1 and 65535".to_owned()); }
    Ok(value)
}

fn healthcheck(port: u16) -> bool {
    let address = format!("127.0.0.1:{port}").parse().unwrap();
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(2)) else { return false; };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    if stream.write_all(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n").is_err() { return false; }
    let mut response = [0_u8; 13];
    stream.read_exact(&mut response).is_ok() && &response == b"HTTP/1.1 200 "
}

fn main() {
    let port = port().unwrap_or_else(|e| { eprintln!("{e}"); std::process::exit(2); });
    if env::args().any(|argument| argument == "--healthcheck") {
        std::process::exit(if healthcheck(port) { 0 } else { 1 });
    }
    let api_key = Arc::new(env::var("BRAIN_API_KEY").ok().filter(|v| !v.is_empty()));
    let (sender, receiver) = mpsc::sync_channel::<TcpStream>(QUEUE_CAPACITY);
    let receiver = Arc::new(Mutex::new(receiver));
    for _ in 0..WORKERS {
        let receiver = Arc::clone(&receiver);
        let api_key = Arc::clone(&api_key);
        thread::spawn(move || loop {
            let stream = receiver.lock().unwrap().recv();
            match stream { Ok(stream) => serve(stream, &api_key), Err(_) => break }
        });
    }
    let listener = TcpListener::bind(("0.0.0.0", port)).unwrap_or_else(|e| { eprintln!("resolver bind failed: {e}"); std::process::exit(1); });
    eprintln!("101XVC BRAIN resolver listening on port {port}");
    for result in listener.incoming() {
        match result {
            Ok(stream) => {
                let _ = stream.set_nodelay(true);
                match sender.try_send(stream) {
                    Ok(()) => {},
                    Err(mpsc::TrySendError::Full(mut stream)) => write_response(&mut stream, 503, &json!({"error":{"code":"busy", "message":"resolver queue is full"}})),
                    Err(mpsc::TrySendError::Disconnected(_)) => break,
                }
            },
            Err(e) => eprintln!("resolver accept error: {e}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Shutdown;

    fn exchange(raw: &str, key: Option<String>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let worker = thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            serve(stream, &key);
        });
        let mut client = TcpStream::connect(address).unwrap();
        client.set_read_timeout(Some(Duration::from_secs(10))).unwrap();
        client.write_all(raw.as_bytes()).unwrap();
        client.shutdown(Shutdown::Write).unwrap();
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        worker.join().unwrap();
        response
    }

    fn post(body: &str, authorization: &str) -> String {
        format!("POST /resolve HTTP/1.1\r\nHost: localhost\r\nContent-Length: {}\r\n{}\r\n{}", body.len(), authorization, body)
    }

    #[test]
    fn key_comparison_and_header_auth() {
        assert!(constant_time_equal(b"abc", b"abc"));
        assert!(!constant_time_equal(b"abc", b"abd"));
        assert!(!constant_time_equal(b"abc", b"abc\0"));
        let mut request = Request { method:"POST".to_owned(), path:"/resolve".to_owned(), headers:HashMap::new(), body:vec![] };
        assert!(!authorized(&request, &Some("secret".to_owned())));
        request.headers.insert("authorization".to_owned(), "Bearer secret".to_owned());
        assert!(authorized(&request, &Some("secret".to_owned())));
        assert!(authorized(&request, &None));
    }

    #[test]
    fn health_is_available_without_credentials() {
        let response = exchange("GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n", Some("testkey".to_owned()));
        assert!(response.starts_with("HTTP/1.1 200 "));
        assert!(response.contains("\"status\":\"ok\""));
    }

    #[test]
    fn resolve_requires_key_when_configured_and_preserves_identity() {
        let body = r#"{"records":[{"county_fips":"08031","parcel_id":"00-001"}]}"#;
        let denied = exchange(&post(body, ""), Some("testkey".to_owned()));
        assert!(denied.starts_with("HTTP/1.1 401 "));
        let accepted = exchange(&post(body, "Authorization: Bearer testkey\r\n"), Some("testkey".to_owned()));
        assert!(accepted.starts_with("HTTP/1.1 200 "));
        assert!(accepted.contains("\"property_id\":\"08031-00001\""));
    }

    #[test]
    fn invalid_batches_and_ambiguous_framing_are_rejected() {
        let invalid = exchange(&post(r#"{"records":[]}"#, ""), None);
        assert!(invalid.starts_with("HTTP/1.1 400 "));
        let duplicate = exchange("POST /resolve HTTP/1.1\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n", None);
        assert!(duplicate.starts_with("HTTP/1.1 400 "));
        assert!(duplicate.contains("duplicate_header"));
        let chunked = exchange("POST /resolve HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", None);
        assert!(chunked.starts_with("HTTP/1.1 400 "));
        let missing_length = exchange("POST /resolve HTTP/1.1\r\nHost: localhost\r\n\r\n", None);
        assert!(missing_length.starts_with("HTTP/1.1 411 "));
        let oversized = exchange("POST /resolve HTTP/1.1\r\nContent-Length: 2097153\r\n\r\n", None);
        assert!(oversized.starts_with("HTTP/1.1 413 "));
    }
}
