# Contributing

Start feature work from the current `main` branch and follow the integration workflow
in the [README](README.md#work-from-the-integrated-main-branch).

## Check your commit identity

Before committing, inspect the identity Git will use in this repository:

```sh
git var GIT_AUTHOR_IDENT
```

If it is incorrect, set your own name and an email linked to your GitHub account
(including your GitHub-provided noreply address, if preferred):

```sh
git config --local user.name "Your name"
git config --local user.email "YOUR_GITHUB_LINKED_EMAIL"
```

These settings apply to future commits. Check a newly created commit with:

```sh
git log -1 --format="%h %an <%ae>"
```

GitHub's repository Contributors graph counts non-empty, non-merge commits on the
default branch whose author email is linked to an account. An empty commit cannot
repair attribution for earlier work. See [GitHub's contributor documentation](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-a-projects-contributors).

## Historical author aliases

The repository's [.mailmap](.mailmap) maps historical author identities to their
canonical names and emails for Git tools such as `git shortlog` and
`git log --use-mailmap`. This preserves existing commit IDs and history; GitHub
account linkage remains a separate requirement. See the [Git mailmap reference](https://git-scm.com/docs/gitmailmap).

Check the mapping after updating an alias:

```sh
git check-mailmap "Name <OLD_COMMIT_EMAIL>"
git shortlog -sne main
```

Add aliases only for identities known to belong to the same contributor.
