# Contributing to thingdir

thingdir is a small, focused directory server. The highest leverage
contributions:

## Add a storage backend

A backend is one class implementing the `Store` protocol in
`src/thingdir/stores/`: `put`, `get`, `delete`, `list`, `page`, `count`,
`search`, `events` and `changes_since`. The last one is the one to read first;
`stores/base.py` says what it has to guarantee, and a derived index is wrong
without it. Each backend is self contained and does not touch the HTTP layer.
Add it, a test, and a line in the README.

## Extend the TDD API

JSONPath and SPARQL search are implemented. The specification also defines
XPath search and richer `/events` filtering, both optional and both welcome
here.

## Ground rules

- Keep it small. The HTTP stack is the `server` extra and every backend is
  opt in, so the base install stays light.
- Tests pass offline: `pytest`. Backend tests skip unless you point
  `THINGDIR_PG_URL`, `THINGDIR_MONGO_URL` or `THINGDIR_REDIS_URL` at a live
  instance, and `THINGDIR_NO_NET=1` skips the one network test.
- `ruff check .` and `ruff format --check .` pass. The version is pinned in
  the `dev` extra so your run matches CI's.
- Match the surrounding style. Plain comments, no fluff.

## Sign your commits (DCO)

This project uses the [Developer Certificate of Origin](DCO) (DCO), not a
CLA. By signing off you certify that you wrote the contribution, or
otherwise have the right to submit it under Apache-2.0.

Add the sign-off with `-s`:

```bash
git commit -s -m "add a CouchDB store"
```

That appends a trailer matching the commit author:

```
Signed-off-by: Your Name <you@example.com>
```

If you forget it, amend with `git commit -s --amend`. Every pull request's
commits must be signed off.

## AI-assisted contributions, and the human behind them

You are welcome to use AI tools to write code here. Many good patches are
drafted with an assistant, and we do not treat that as a problem. What we
require is simple and it follows straight from the sign-off above: a real
person stands behind every contribution.

The sign-off is not a formality. When you add `Signed-off-by`, you are
certifying, under the Developer Certificate of Origin, that you have the right
to submit the work and that you take responsibility for it. An AI tool cannot
make that certification. A person can. So:

- The `Signed-off-by` name and email must be a real human's, reachable and
  accountable. Not a tool's name, not a bot account, not an alias created to
  farm contributions.
- You are responsible for what you submit, whether you typed it or an assistant
  did. "The model wrote it" is not an answer to a review question. Read your
  own patch, understand it, and be able to explain why it is correct.
- Test it yourself before you open the PR. Run `pytest` and
  the relevant example. A patch that only compiles in theory wastes a review.
- Disclose heavy AI involvement if it helps a reviewer, for example if a large
  change was generated. A one-line note in the PR is enough. This is courtesy,
  not a confession; the point is an honest, reviewable history.

What we will not accept: automated or drive-by pull requests opened by a bot or
a scripted account, patches submitted purely to inflate a contribution count,
and PRs whose author cannot answer questions about their own change. These
waste maintainer time and we close them, however clean the diff looks. The bar
is a human who understands and vouches for the work, not the absence of AI.

If you are a real person new to the project and used an assistant, you are
exactly who this section is for. Sign off, claim the issue, and say hello.

## Claiming an issue first

Before you open a pull request, comment on the issue to claim it, so two people
do not build the same thing. A maintainer will confirm. This also lets us point
you at anything the issue does not spell out. Unclaimed PRs may be closed,
especially on a well-scoped issue that someone else already claimed.

## Where to start

Adding a store for a backend thingdir cannot yet reach is scoped, testable, and
immediately useful. See the open issues labeled
[`good first issue`](https://github.com/thingctx/thingdir/labels/good%20first%20issue)
or [`help wanted`](https://github.com/thingctx/thingdir/labels/help%20wanted),
claim one, and go.

## Asking before you build

Not everything needs an issue. If you want to know whether thingdir already
does something, whether an idea fits, or how a backend should behave,
[Discussions](https://github.com/thingctx/thingdir/discussions) is the place,
and a question there is welcome on its own.
