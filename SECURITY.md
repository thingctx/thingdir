# Security

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the Security tab) rather than opening a public
issue. We aim to acknowledge reports within a few business days.

## What this software is, in security terms

thingdir serves and stores W3C Thing Descriptions. A Thing Description says how
to reach a device: URLs, protocols, and which security scheme a caller has to
satisfy. It does not carry the secret itself.

Two consequences worth stating plainly.

**A directory is a map of your fleet.** Read access tells the reader what
devices exist and where they are. Treat the read surface as sensitive even
though it holds no credentials.

**Writes decide what agents will drive.** A consumer reads a description and
acts on it, so whoever can write to the directory can change where a call goes.
That is why writes are gated and reads are not.

## The authorization model

One switch. With a write token configured, `POST`, `PUT`, `DELETE` and
`POST /admin/prune` require `Authorization: Bearer <token>` and answer `401`
without it. Reads are always open.

That is the floor, not a fleet authorization system, and it is meant to be read
that way. WoT Discovery 7.1.2 leaves the mechanism to the deployment. If you
need per caller authorization, put a gateway in front that does it properly and
keep thingdir behind it.

There is no TLS in thingdir itself. Terminate it in front.

## Not attack surface, deliberately

The SPARQL endpoint evaluates queries only. `INSERT`, `DELETE` and `DROP` are
refused with a 400 and cannot reach the store; `tests/test_sparql_conformance.py`
asserts the triple count is unchanged after each attempt.

Validation, with the `validate` extra, checks a document against the W3C TD 1.1
schema before it is stored. That is a conformance check, not a trust decision: a
valid Thing Description can still point anywhere.

## Supported versions

Pre 1.0, the latest release is the supported one.
