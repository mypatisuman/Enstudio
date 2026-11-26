# Credential exposure — required rotation

**Status: the source tree is clean. The credentials themselves are still live
and must be rotated by hand.**

Removing a secret from the source does not make it safe. Everything listed
below was readable in plaintext in the working tree and must be treated as
compromised.

## What was exposed

`mongo.env`, in the repository root, held roughly thirty production secrets in
plaintext. The `.gitignore` patterns `.env` and `**/.env` match only a file
named exactly `.env`, so `mongo.env` was never ignored.

| Secret | Key | Risk if used |
|---|---|---|
| MongoDB / CosmosDB | `MONGODB_URI`, `RESTRUCTURED_DB_URI` | Full read/write on the production cluster |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Payment operations, forged webhooks |
| Azure Storage | `AZURE_STORAGE_ACCOUNT_KEY`, `AzureWebJobsStorage` | Full blob read/write |
| Azure AD | `AZURE_CLIENT_SECRET` | Application impersonation |
| Azure Redis | `REDIS_KEY`, `REDIS_PASSWORD`, `REDIS_URL` | Cache read/write |
| SMTP | `SMTP_PASSWORD` | Send mail as `support@engenieai.com` |
| Session signing | `SECRET_KEY`, `JWT_SECRET_KEY` | Forge sessions and tokens |
| Third-party APIs | `DEEPINFRA_API_KEY`, `HUGGINGFACE_API_KEY`, `SERPAPI_KEY`, `SERPER_API_KEY`, `LANGSMITH_API_KEY` | Billable usage on your accounts |
| Commented-out lines | `DATABASE_URL`, `GOOGLE_API_KEY`, `OPEN_API_KEY`, `REPLICATE_API_TOKEN`, `AZURE_KIMI_API_KEY` | Still live; a `#` hides nothing |

The MongoDB connection string, password included, was additionally hardcoded as
a default value in two source files:

- `backend/adapters/mongodb.py`
- `backend/scripts/init_enstudio_db.py`

Any checkout could therefore reach the production cluster with no configuration
at all, and the seeder could **write** to it.

## What was changed

1. `.gitignore` now ignores every `*.env` file and whitelists only
   `*.env.example`.
2. `mongo.env.example` documents all key names with every value blanked,
   including on commented-out lines.
3. `adapters/mongodb.py` has no default URI. An unset `MONGODB_URI` raises
   `MissingMongoCredentials` at call time, with a message pointing at the
   template. The check is deliberately not at import time, so tooling can still
   import the module on a machine with no Mongo configured.
4. `scripts/init_enstudio_db.py` exits with an explanatory message rather than
   defaulting to a cluster.
5. `tests/test_credentials_and_resolve.py` scans the whole tree on every test
   run and fails if any of these credential fragments reappears.

`mongo.env` itself was left in place so local development keeps working. It is
now ignored.

## What you still have to do

Rotation is the only thing that makes the exposure harmless. In rough priority
order:

1. **Stripe** — roll the secret key and the webhook signing secret in the
   Stripe dashboard.
2. **Azure** — regenerate both storage account keys, the AD client secret, and
   the Redis access keys.
3. **MongoDB / CosmosDB** — change the `Ensar` account password and update
   `MONGODB_URI` and `RESTRUCTURED_DB_URI`.
4. **SMTP** — change the `support@engenieai.com` mailbox password.
5. **Signing secrets** — generate new `SECRET_KEY` and `JWT_SECRET_KEY` values.
   Rotating these invalidates existing sessions and tokens, which is the point.
6. **Third-party API keys** — revoke and reissue DeepInfra, HuggingFace,
   SerpAPI, Serper and LangSmith.

If this tree was ever pushed to a remote, rotation is not optional and the
history needs scrubbing as well: removing the file in a new commit leaves every
earlier commit readable.

## Keeping it clean

- Secrets belong in `mongo.env` or `backend/.env`, both ignored. Commit only
  the `.example` templates.
- Commenting a line out does not redact it. Blank the value.
- `tests/test_credentials_and_resolve.py::test_no_committed_secret_in_any_source_file`
  is the regression guard. Extend `_LEAKED_FRAGMENTS` when new secrets are
  rotated in, so a future paste is caught by the suite.
