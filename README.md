# Data Analytics MCP Hub

[中文说明](README.zh-CN.md)

MCP servers connecting AI clients to MySQL and Hive through stdio or SSE, with a local Gradio management interface.

![Management interface](docs/images/001.png)

## Capabilities

- List tables, inspect schemas and query plans.
- Execute query tools and inspect Hive partitions.
- Configure connections and test tools in a local UI.
- Cache results and apply basic SQL safety checks.

## Quick start

Use a supported Python environment and a disposable or read-only database. See the requirements files for dependencies; Hive also requires system SASL libraries.

```bash
git clone https://github.com/albertyuee/MCP_Hub.git
cd MCP_Hub
cp .env.example .env
```

Set database configuration in `.env`, then run `bash start.sh`. The local UI runs at `http://localhost:7860`. See the [detailed guide](README.zh-CN.md) for client configuration and Hive setup. Transport compatibility depends on the client version.

## Data flow and boundaries

```text
Database → MCP server → AI client → configured model provider
```

Running the database and MCP server in a private network **does not guarantee that results remain inside that network**. The client may send tool output to an external model.

- Restrict database credentials to approved read-only data.
- Basic SQL checks are not a database sandbox or substitute for access control.
- Review client and provider behavior before using confidential records.
- Do not expose the UI or SSE service publicly without authentication, TLS and network restrictions.
- Use synthetic data for demonstrations.

## Project structure

| Directory | Responsibility |
| --- | --- |
| `servers/mysql_mcp/` | MySQL tools and transports |
| `servers/hive_mcp/` | Hive tools and transports |
| `shared/` | Validation, caching and schema helpers |
| `web/` | Gradio interface |
| `examples/` | Integration examples |

## Status and license

Prototype integration project. No production deployment, benchmark or end-to-end compatibility matrix is claimed. Test examples against your client and dependency versions.

MIT. See [LICENSE](LICENSE).
