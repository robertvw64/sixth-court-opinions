# Texas Sixth Court of Appeals: daily orders and opinions

A GitHub Action that runs every weekday evening. It checks
[Released Orders/Opinions](https://search.txcourts.gov/DocketSrch.aspx?coa=coa06),
downloads the PDFs for any release date it hasn't saved yet, and commits them to
this repository under:

    opinions/Orders and Opinions for <Month D, YYYY>/
        06-26-00046-CV.pdf
        ...
        index.md   <- case, style, court below, disposition, author, panel

## One-time setup

1. Sign in at github.com and create a new repository (Private is fine), e.g.
   `sixth-court-opinions`.
2. On the repository page choose **Add file → Upload files** and drag in the
   contents of this folder, keeping the `.github` folder (it holds
   `.github/workflows/fetch.yml`). Commit.
   *Windows hides folders starting with a dot in some views; if `.github`
   doesn't upload, create the file in the browser instead: Add file → Create
   new file, name it `.github/workflows/fetch.yml`, and paste the contents.*
3. Go to **Settings → Actions → General → Workflow permissions**, select
   **Read and write permissions**, and Save.
4. Go to the **Actions** tab, pick **Fetch Sixth Court opinions**, and click
   **Run workflow** to test it now. When it finishes, the `opinions` folder
   appears in the repository.

## Using it

- The schedule is weekdays at 23:30 UTC (6:30 pm Central in summer, 5:30 pm in
  winter). Edit the `cron` line in `.github/workflows/fetch.yml` to change it.
- To fetch one particular date, use **Run workflow** and type the date as
  `MM/DD/YYYY`.
- The court's page only lists its most recent release dates (about the last
  five), so dates older than that can't be fetched from the list.
- Files can be read on github.com from any device, or downloaded with
  **Code → Download ZIP**.
- GitHub turns off scheduled workflows in a repository with no activity for 60
  days. The daily commits normally count as activity; if it's ever disabled,
  re-enable it on the Actions tab.

## Notes

- The script waits 2 seconds between requests and only fetches the date pages
  and PDFs it needs.
- `tests/` holds saved copies of the court's pages for checking the parser:
  `python tests/test_parse.py`.
