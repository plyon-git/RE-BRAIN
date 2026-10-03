use brain_resolver::{resolve_record, CanonicalRecord};
use serde_json::Value;

#[test]
fn golden_identity_contract() {
    let fixture: Value = serde_json::from_str(include_str!("identity_golden.json")).unwrap();
    for case in fixture["valid"].as_array().unwrap() {
        let record: CanonicalRecord = serde_json::from_value(case["record"].clone()).unwrap();
        let actual = serde_json::to_value(resolve_record(&record).unwrap()).unwrap();
        assert_eq!(actual, case["expected"], "{}", case["name"]);
    }
    for case in fixture["invalid"].as_array().unwrap() {
        if let Ok(record) = serde_json::from_value::<CanonicalRecord>(case["record"].clone()) {
            assert!(resolve_record(&record).is_err(), "{}", case["name"]);
        }
    }
}
