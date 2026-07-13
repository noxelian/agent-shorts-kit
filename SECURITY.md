# Security policy

## Secrets

The default workflow needs no secret. Optional provider keys belong in `.env`
or the process environment. YouTube OAuth material belongs only in
`pipeline/credentials.json` and `pipeline/token.json`. All are ignored by git.

Before publishing a fork, run:

```bash
git status --short
git grep -nE '(API[_-]?KEY|SECRET|TOKEN|BEGIN (RSA|OPENSSH|PRIVATE))'
```

Inspect every match. Placeholder names are expected; credential values are not.

## Generated media

Episode directories may contain private topics, licensed assets, cloned voices,
or unpublished videos. They are ignored by default. Add only deliberately
cleared examples to a public fork.

## Reporting

Open a private security advisory in the repository hosting this project. Do not
post active credentials in a public issue.

