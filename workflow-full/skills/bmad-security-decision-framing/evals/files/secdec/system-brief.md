# Inbox Concierge — system brief

## What it is

A single LLM agent ("Concierge") that manages the user's email end to end:
triages new mail, summarizes linked pages, drafts and sends replies, and pays
incoming invoices it judges legitimate.

## Components & tools

- **mail-read** — IMAP read access to the entire mailbox. The mailbox is the
  user's private data; the *bodies* of incoming messages are third-party
  content of unknown origin.
- **web-fetch** — fetches arbitrary URLs found in emails so the agent can
  summarize linked pages. Fetched page content is third-party content.
- **mail-send** — sends email as the user (any recipient, any content).
- **pay-invoice** — calls the Acme Payments API to pay an invoice, up to
  $2,000 per invoice, drawn from the company account.

## Current architecture

One agent, one context window. On each new message the Concierge reads the
mail, fetches any linked pages, then decides whether to reply (mail-send)
and/or pay (pay-invoice). There is no human approval step on send or pay
today. All four tools are available to the agent in every turn.

## Assets

- Mailbox contents: contracts, password-reset emails, customer threads.
- The payments account (auto-pay authority up to $2,000 per invoice).
- The user's outbound identity (mail sent as them is trusted by recipients).

## Open decision

How do we restructure capabilities so that a prompt-injected email or web
page cannot exfiltrate mailbox contents or trigger a payment? Ideas floated
but not decided: split the agent somehow, strip capabilities, add approval
gates. Nothing is chosen yet.

## Known constraints

- Replies to routine scheduling email must stay low-friction (a human
  approval click on every reply would kill the product).
- Infrastructure budget allows at most two concurrently running model
  instances.
