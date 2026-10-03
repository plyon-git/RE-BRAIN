//! County-scoped, deterministic identity contract shared with the Python API.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const IDENTITY_CONTRACT_VERSION: &str = "1";
pub const MAX_BATCH_RECORDS: usize = 10_000;

#[derive(Debug, Deserialize)]
pub struct ResolveRequest {
    pub records: Vec<CanonicalRecord>,
}

/// Additional canonical-record fields are deliberately accepted and ignored.
#[derive(Debug, Deserialize)]
pub struct CanonicalRecord {
    pub county_fips: String,
    #[serde(default)]
    pub parcel_id: Option<String>,
    #[serde(default)]
    pub address: Option<String>,
    #[serde(default)]
    pub state: Option<String>,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct ResolvedIdentity {
    pub property_id: String,
    pub normalized_parcel_id: String,
    pub address_key: String,
}

#[derive(Debug, Serialize)]
pub struct ResolveResponse {
    pub results: Vec<ResolvedIdentity>,
}

#[derive(Debug, Serialize)]
pub struct ValidationError {
    pub code: &'static str,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub record_index: Option<usize>,
}

impl ValidationError {
    fn record(message: &str) -> Self {
        Self { code: "invalid_record", message: message.to_owned(), record_index: None }
    }
}

/// Uppercase before filtering so Unicode uppercase expansions match Python.
/// The retained alphabet is intentionally ASCII A-Z and 0-9.
pub fn normalize_parcel(value: &str) -> String {
    value.chars().flat_map(char::to_uppercase)
        .filter(|c| c.is_ascii_alphanumeric()).collect()
}

/// Punctuation is a word separator. No street abbreviations are inferred.
pub fn normalize_address(value: &str) -> String {
    let spaced: String = value.chars().flat_map(char::to_uppercase)
        .map(|c| if c.is_ascii_alphanumeric() { c } else { ' ' }).collect();
    spaced.split_ascii_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn resolve_record(record: &CanonicalRecord) -> Result<ResolvedIdentity, ValidationError> {
    if record.county_fips.len() != 5 || !record.county_fips.bytes().all(|c| c.is_ascii_digit()) {
        return Err(ValidationError::record("county_fips must be exactly five ASCII digits"));
    }
    let raw_parcel = record.parcel_id.as_deref().unwrap_or("");
    let raw_address = record.address.as_deref().unwrap_or("");
    let raw_state = record.state.as_deref().unwrap_or("");
    if raw_parcel.len() > 128 {
        return Err(ValidationError::record("parcel_id must contain at most 128 UTF-8 bytes"));
    }
    if raw_address.len() > 512 {
        return Err(ValidationError::record("address must contain at most 512 UTF-8 bytes"));
    }
    if raw_state.len() > 32 {
        return Err(ValidationError::record("state must contain at most 32 UTF-8 bytes"));
    }
    let state = raw_state.trim().to_uppercase();
    if !state.is_empty() && (state.len() != 2 || !state.bytes().all(|c| c.is_ascii_uppercase())) {
        return Err(ValidationError::record("state must be an ASCII two-letter abbreviation when provided"));
    }
    let normalized_parcel_id = normalize_parcel(raw_parcel);
    let normalized_address = normalize_address(raw_address);
    let address_key = if state.is_empty() {
        normalized_address.clone()
    } else {
        format!("{}|{}", normalized_address, state)
    };
    let property_id = if normalized_parcel_id.is_empty() {
        if normalized_address.is_empty() || state.is_empty() {
            return Err(ValidationError::record("an empty parcel_id requires a nonempty address and a two-letter state"));
        }
        let digest = Sha256::digest(address_key.as_bytes());
        let hash: String = digest[..10].iter().map(|b| format!("{b:02x}")).collect();
        format!("{}-ADDR-{}", record.county_fips, hash)
    } else {
        format!("{}-{}", record.county_fips, normalized_parcel_id)
    };
    Ok(ResolvedIdentity { property_id, normalized_parcel_id, address_key })
}

/// All-or-nothing validation preserves exact input/output correspondence.
pub fn resolve_batch(request: &ResolveRequest) -> Result<ResolveResponse, ValidationError> {
    if request.records.is_empty() {
        return Err(ValidationError { code: "empty_batch", message: "records must not be empty".to_owned(), record_index: None });
    }
    if request.records.len() > MAX_BATCH_RECORDS {
        return Err(ValidationError { code: "batch_too_large", message: format!("records may contain at most {MAX_BATCH_RECORDS} items"), record_index: None });
    }
    let results = request.records.iter().enumerate().map(|(index, record)| {
        resolve_record(record).map_err(|mut error| { error.record_index = Some(index); error })
    }).collect::<Result<Vec<_>, _>>()?;
    Ok(ResolveResponse { results })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(county: &str, parcel: &str, address: &str, state: &str) -> CanonicalRecord {
        CanonicalRecord { county_fips: county.to_owned(), parcel_id: Some(parcel.to_owned()), address: Some(address.to_owned()), state: Some(state.to_owned()) }
    }

    #[test]
    fn parcel_keeps_leading_zeros_and_drops_punctuation() {
        let resolved = resolve_record(&record("08031", "00-01. a / 07", "123 Main St.", " co ")).unwrap();
        assert_eq!(resolved.property_id, "08031-0001A07");
        assert_eq!(resolved.address_key, "123 MAIN ST|CO");
        assert_eq!(normalize_parcel("00000"), "00000");
    }

    #[test]
    fn county_prevents_cross_county_merges() {
        let a = resolve_record(&record("08031", "000123", "1 Main", "CO")).unwrap();
        let b = resolve_record(&record("08059", "000123", "1 Main", "CO")).unwrap();
        assert_ne!(a.property_id, b.property_id);
    }

    #[test]
    fn address_fallback_is_repeatable_and_state_scoped() {
        let a = resolve_record(&record("08031", "", "123 Main St., Apt #4", "co")).unwrap();
        let b = resolve_record(&record("08031", "--", " 123 MAIN ST APT 4 ", "CO")).unwrap();
        assert_eq!(a, b);
        assert_eq!(a.address_key, "123 MAIN ST APT 4|CO");
        assert_eq!(a.property_id.len(), 31);
        assert!(a.property_id.starts_with("08031-ADDR-"));
        let c = resolve_record(&record("08031", "", "123 Main St., Apt #4", "TX")).unwrap();
        assert_ne!(a.property_id, c.property_id);
    }

    #[test]
    fn blank_or_malformed_identity_is_rejected() {
        for county in ["", "8031", "080310", "08A31", " 8031", "٠٨٠٣١"] {
            assert!(resolve_record(&record(county, "123", "123 Main", "CO")).is_err());
        }
        assert!(resolve_record(&record("08031", "", "", "CO")).is_err());
        assert!(resolve_record(&record("08031", "", "123 Main", "")).is_err());
        assert!(resolve_record(&record("08031", "123", "123 Main", "Colorado")).is_err());
    }

    #[test]
    fn duplicates_are_retained_one_to_one() {
        let request: ResolveRequest = serde_json::from_str(r#"{"records":[{"county_fips":"08031","parcel_id":"00001"},{"county_fips":"08031","parcel_id":"00001"}]}"#).unwrap();
        let response = resolve_batch(&request).unwrap();
        assert_eq!(response.results.len(), 2);
        assert_eq!(response.results[0], response.results[1]);
    }

    #[test]
    fn batch_errors_report_input_index() {
        let request = ResolveRequest { records: vec![record("08031", "123", "", ""), record("bad", "456", "", "")] };
        assert_eq!(resolve_batch(&request).unwrap_err().record_index, Some(1));
        assert_eq!(resolve_batch(&ResolveRequest { records: vec![] }).unwrap_err().code, "empty_batch");
    }

    #[test]
    fn normalized_unicode_has_explicit_ascii_contract() {
        assert_eq!(normalize_parcel("00-ß-ı"), "00SSI");
        assert_eq!(normalize_address("Café / Straße"), "CAF STRASSE");
    }
}
