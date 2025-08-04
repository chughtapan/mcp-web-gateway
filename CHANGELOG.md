# Changelog

## [0.0.0dev] - 2025-07-26

### Added
- Initial release of MCP Web Gateway
- Web gateway approach for OpenAPI integration with Model Context Protocol (MCP)
- Expose all HTTP routes as MCP resources with original HTTP URIs
- Generic REST tools: GET, POST, PUT, PATCH, DELETE
- URI prefixes to handle multiple methods on the same path
- Custom resource implementations (WebResource/WebResourceTemplate)
- Comprehensive test suite with unit and integration tests
- Example implementation demonstrating usage

### Features
- Resources use HTTP URIs with method prefixes (e.g., `https+get://api.example.com/users`)
- Resources act as metadata containers (read-only by design)
- Array responses wrapped in `{"result": [...]}` for consistency
- Method validation when URL includes method prefix
- HTTP metadata preserved in resource annotations