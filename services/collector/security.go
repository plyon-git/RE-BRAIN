package main

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strings"
	"time"
)

type URLPolicy struct{ allowedHosts map[string]bool }

func NewURLPolicy(hosts []string) *URLPolicy {
	policy := &URLPolicy{allowedHosts: make(map[string]bool)}
	for _, host := range hosts {
		host = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(host)), ".")
		if host != "" {
			policy.allowedHosts[host] = true
		}
	}
	return policy
}

func (p *URLPolicy) Validate(target string) (*url.URL, error) {
	parsed, err := url.Parse(target)
	if err != nil {
		return nil, errors.New("Invalid source URL")
	}
	if parsed.Scheme != "https" {
		return nil, errors.New("Only HTTPS source URLs are allowed")
	}
	if parsed.User != nil || parsed.Fragment != "" {
		return nil, errors.New("URL credentials and fragments are not allowed")
	}
	host := strings.TrimSuffix(strings.ToLower(parsed.Hostname()), ".")
	if host == "" || net.ParseIP(host) != nil {
		return nil, errors.New("Source URLs must use an allowlisted DNS hostname")
	}
	if parsed.Port() != "" && parsed.Port() != "443" {
		return nil, errors.New("Only HTTPS port 443 is allowed")
	}
	if !p.allowedHosts[host] {
		return nil, errors.New("Source hostname is not in COLLECTOR_ALLOWED_HOSTS")
	}
	return parsed, nil
}

var blockedRanges = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"), netip.MustParsePrefix("10.0.0.0/8"),
	netip.MustParsePrefix("100.64.0.0/10"), netip.MustParsePrefix("127.0.0.0/8"),
	netip.MustParsePrefix("169.254.0.0/16"), netip.MustParsePrefix("172.16.0.0/12"),
	netip.MustParsePrefix("192.0.0.0/24"), netip.MustParsePrefix("192.0.2.0/24"),
	netip.MustParsePrefix("192.168.0.0/16"), netip.MustParsePrefix("198.18.0.0/15"),
	netip.MustParsePrefix("198.51.100.0/24"), netip.MustParsePrefix("203.0.113.0/24"),
	netip.MustParsePrefix("224.0.0.0/4"), netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("::/96"), netip.MustParsePrefix("::ffff:0:0/96"),
	netip.MustParsePrefix("64:ff9b::/96"), netip.MustParsePrefix("64:ff9b:1::/48"),
	netip.MustParsePrefix("100::/64"), netip.MustParsePrefix("2001::/23"),
	netip.MustParsePrefix("2001:db8::/32"), netip.MustParsePrefix("2002::/16"),
	netip.MustParsePrefix("fc00::/7"), netip.MustParsePrefix("fe80::/10"),
	netip.MustParsePrefix("ff00::/8"),
}

func isPublicIP(ip net.IP) bool {
	address, ok := netip.AddrFromSlice(ip)
	if !ok {
		return false
	}
	address = address.Unmap()
	if !address.IsGlobalUnicast() || address.IsPrivate() || address.IsLoopback() || address.IsLinkLocalUnicast() {
		return false
	}
	for _, prefix := range blockedRanges {
		if prefix.Contains(address) {
			return false
		}
	}
	// Public IPv6 currently allocated for unicast lies within 2000::/3.
	if address.Is6() && !netip.MustParsePrefix("2000::/3").Contains(address) {
		return false
	}
	return true
}

func newHTTPClient(policy *URLPolicy) *http.Client {
	dialer := &net.Dialer{Timeout: 8 * time.Second, KeepAlive: 30 * time.Second}
	transport := &http.Transport{
		Proxy:                 nil,
		TLSClientConfig:       &tls.Config{MinVersion: tls.VersionTLS12},
		TLSHandshakeTimeout:   8 * time.Second,
		ResponseHeaderTimeout: 12 * time.Second,
		MaxIdleConns:          8,
		MaxIdleConnsPerHost:   2,
		MaxConnsPerHost:       4,
		IdleConnTimeout:       30 * time.Second,
		DisableCompression:    true,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			host, port, err := net.SplitHostPort(address)
			if err != nil {
				return nil, errors.New("Invalid upstream address")
			}
			if _, err := policy.Validate("https://" + net.JoinHostPort(host, port)); err != nil {
				return nil, err
			}
			resolved, err := net.DefaultResolver.LookupIPAddr(ctx, host)
			if err != nil || len(resolved) == 0 {
				return nil, errors.New("Source DNS lookup failed")
			}
			// Reject the whole lookup if even one answer targets an internal/reserved network.
			for _, candidate := range resolved {
				if !isPublicIP(candidate.IP) {
					return nil, errors.New("Source DNS resolved to a private or reserved address")
				}
			}
			var lastErr error
			for _, candidate := range resolved {
				// Dial the checked IP directly to eliminate a second, rebindable DNS lookup.
				connection, err := dialer.DialContext(ctx, network, net.JoinHostPort(candidate.IP.String(), port))
				if err == nil {
					return connection, nil
				}
				lastErr = err
			}
			return nil, fmt.Errorf("Source connection failed: %w", lastErr)
		},
	}
	return &http.Client{Transport: transport, Timeout: 20 * time.Second, CheckRedirect: func(request *http.Request, via []*http.Request) error {
		if len(via) >= 5 {
			return errors.New("Too many source redirects")
		}
		_, err := policy.Validate(request.URL.String())
		return err
	}}
}

func fetchURL(ctx context.Context, client *http.Client, policy *URLPolicy, target string) ([]byte, error) {
	if _, err := policy.Validate(target); err != nil {
		return nil, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, errors.New("Unable to create source request")
	}
	request.Header.Set("Accept", "application/json,text/csv;q=0.9,text/plain;q=0.8")
	request.Header.Set("User-Agent", "101XVC-BRAIN-Collector/1.0")
	response, err := client.Do(request)
	if err != nil {
		return nil, errors.New("Source request failed: " + safeNetworkError(err))
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("Source returned HTTP %d", response.StatusCode)
	}
	if response.ContentLength > maxResponseBytes {
		return nil, errors.New("Source response exceeds 16 MiB")
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes+1))
	if err != nil {
		return nil, errors.New("Unable to read source response")
	}
	if len(body) > maxResponseBytes {
		return nil, errors.New("Source response exceeds 16 MiB")
	}
	return body, nil
}

func safeNetworkError(err error) string {
	// http.Client wraps errors with full URLs, including query credentials.
	var urlErr *url.Error
	if errors.As(err, &urlErr) {
		err = urlErr.Err
	}
	var timeout net.Error
	if errors.As(err, &timeout) && timeout.Timeout() {
		return "upstream timeout"
	}
	message := err.Error()
	if len(message) > 250 {
		message = message[:250]
	}
	return message
}
