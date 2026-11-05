# Texas Sixth Court of Appeals: daily orders and opinions

A GitHub Action that runs every weekday at 16:00 UTC. It checks
[Released Orders/Opinions](https://search.txcourts.gov/DocketSrch.aspx?coa=coa06),
downloads the PDFs for any release date it hasn't saved yet, summarizes them with
Claude, and commits the results to this repository under:

    opinions/mm_dd_yyyy/
        06-26-00046-CV.pdf
        ...
        index.md   <- case, style, court below, disposition, author, panel
        yyyy-mm-dd-opinions-summary.docx   <- the day's Daily Brief summaries
        summaries/
            06-26-00046-CV.json   <- one saved JSON entry per PDF (see json-contract.md)

## Summaries

The summary step runs only when the `ANTHROPIC_API_KEY` secret is set. It also needs
the `CLAUDE_SKILL_ID` secret, the ID of the uploaded `appellate-ruling-summary-json`
skill. The pinned skill version and the model are set in `.github/workflows/fetch.yaml`;
update `CLAUDE_SKILL_VERSION` there after uploading a new version of the skill.

- A ruling with a saved JSON entry is not sent to Claude again. To redo one, delete its
  JSON file and rerun the workflow; the Word document is rebuilt automatically.
- If an API request fails, the ruling is listed as an error in the document and retried
  on the next run, and the run shows as failed. PDFs and finished summaries are still
  committed.
- Rulings Claude couldn't summarize, including refusals, are saved as `error` entries
  and listed under "Not summarized." They are not retried automatically.
