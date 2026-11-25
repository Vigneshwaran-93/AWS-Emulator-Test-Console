# AWS Emulator Test Console

A small Flask app for installing, running and exercising the [AWS Emulator](https://aws.amazon.com/products/developer-tools/emulator/)
(released Nov 2026) with a live request/response monitor.

    run.bat                 # Windows; creates .venv on first run, then opens http://127.0.0.1:5055
    # or, any OS:
    python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python app.py

Requires Python 3.10+ and Docker. The emulator is Linux-native, so on Windows/macOS the app runs it in a Docker container for you.

## What you get

* **Left half** - Install & Setup (about, build the image, start/stop, connect CLI/SDK, coverage probe), then one page per
  service with multi-step scenarios and editable single-call forms, plus cross-service workflows.
* **Right half** - Call Monitor with every call's request and response. Capture mode toggle:
  *SDK hooks* (boto3 events), *Logging proxy* (wire level, port 9390, also records your own CLI/SDK calls), or *Both*.
* **15 services** - S3, DynamoDB, SQS, Lambda, IAM/STS, Secrets Manager; Bedrock, Bedrock Runtime, Bedrock Agents,
  Comprehend, Translate, Textract, Rekognition, Polly, SageMaker.

The emulator runs no ML models: inference returns stub content, a few operations return HTTP 501
(e.g. Comprehend `DetectKeyPhrases`, Translate `ListLanguages`, Rekognition `DetectText`), and Bedrock Agents creation
is in maintenance mode. The pages show these results as-is.

## Security notes

This is a **local development tool**, not a service. Do not expose it to a network.

* **Loopback only, no login.** The console (`127.0.0.1:5055`) and the proxy (`127.0.0.1:9390`) bind to localhost.
  The console rejects requests whose `Host` is not loopback (DNS rebinding), cross-site `Origin`s (CSRF) and non-JSON POSTs,
  and validates the port / memory / timeout you submit before passing them to Docker.
* **Supply chain.** The Docker build downloads the emulator RPM from `downloads.aws.com` and **verifies its GPG signature**:
  the build checks the signing key's fingerprint (`98BC F336 A3BE 53B7 34E9 67C5 2E5B F49B D940 F624`), then runs
  `gpg --verify` on the package; any mismatch fails the build. See `dockerfile_text()` in `emu/docker_ctl.py`.
* **Trace export contains credentials.** *Export JSON* in the monitor includes raw request headers, i.e. SigV4 signatures and the
  emulator's temporary access key (`EMULATOR...`). The keys stop working when the emulator stops, but never paste an export into a public
  issue or chat. The UI asks for confirmation before exporting.
* **Credentials live outside the project.** The emulator writes its generated keys and CA to `~/.aws/emulator/<port>/`
  (files are removed on a clean stop). Nothing secret is stored in this repository.
* **Telemetry.** The emulator reports usage data to AWS by default; this app starts it with `-t off` unless you tick *Telemetry*.
* **Dependencies** are pinned in `requirements.txt` and were audited with `pip-audit` (no known vulnerabilities at release).
  Re-run `pip install pip-audit && pip-audit -r requirements.txt` before upgrading or redeploying.
* **Not affiliated with AWS.** The emulator is distributed by AWS under its own terms (CC0 1.0; `vendor/` under Apache-2.0).
  This project only drives it.

## Reporting bugs and issues

Found a bug, a confusing screen or a missing feature? Please **open an issue** on this repository's *Issues* tab - reports are welcome
and make the tool better for everyone.

**First, decide where it belongs**

| What you saw | Where to report |
|---|---|
| The console itself misbehaves (UI glitch, wrong result display, Docker start/stop fails, monitor missing calls, crash) | An issue **here** |
| The emulator answers differently from real AWS (wrong result, wrong error, an operation you expected to work returns 501) | The emulator's own repo: <https://github.com/aws/aws-emulator>. Include the request you sent, the response you got and the response AWS returns. A 501 is documented behavior for unimplemented operations, so check the [fidelity report](https://docs.aws.amazon.com/emulator/latest/userguide/fidelity.html) first |
| A security problem in this console | Do **not** open a public issue - contact the maintainer privately (GitHub *Security* tab > *Report a vulnerability*, if enabled) |

**What to include in an issue here**

1. What you did (page, form or scenario, and the values you entered) and what you expected.
2. What happened instead, with the exact error text or a screenshot.
3. The relevant rows from the Call Monitor (expand a row and copy its request/response). *Capture mode* (SDK / proxy / both) helps too.
4. Your setup: OS, Python version (`python --version`), Docker version (`docker --version`), and the emulator version
   (`docker run --rm aws-emulator -v`).
5. The container log if the emulator would not start (Run & control > *Show last 120 lines*).

**Before you paste anything, remove secrets.** Monitor rows and the *Export JSON* file contain SigV4 signatures and the emulator's temporary
access key. Redact the `Authorization` header and any `EMULATOR...` access key and secret. Never post your real AWS credentials anywhere.

## License

MIT - see [LICENSE](LICENSE).
