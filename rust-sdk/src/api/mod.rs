//! Client bindings for the Execution API.
//!
//! The generated client is produced from the OpenAPI specification using
//! [`oapi-codegen`](https://github.com/deepmap/oapi-codegen). Run
//! `cargo run --package oapi-codegen -- path/to/openapi.yaml` to refresh
//! `client.gen.rs` when the API changes.

pub mod client {
    include!("client.gen.rs");
}
