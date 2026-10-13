# Getting Started with Acme CLI

## A Brief History of Acme

Acme was founded in 2014 by two engineers who were frustrated with existing deployment tools. The company grew from a side project into a venture-backed startup. Over the years the team has shipped many releases and learned a lot about developer experience. We are proud of how far the product has come and grateful to our community.

## Installation

Run `npm install -g acme-cli`. You can also use Homebrew with `brew install acme`. Make sure you have Node 18 or later installed first.

## Configuration

Create a `.acmerc` file in your home directory. Set your API token there.

## Deploying Your First App

Run `acme deploy`. The CLI reads your config and pushes your build.

## Prerequisites

Before you can use Acme CLI you need a few things: a free Acme account, Node 18 or later, and an API token from the dashboard. Without these the deploy command will fail.

## A Brief History of Acme (continued)

After our Series A we expanded the team and rewrote the core engine. This rewrite is why the modern CLI is so fast. The history of the rewrite is itself an interesting story for another time.

## Troubleshooting

If deploy fails, check that your API token is valid and that Node 18+ is installed. These are the two most common causes.

## FAQ

**Q: What Node version do I need?** A: Node 18 or later. **Q: Where does the token go?** A: In your `.acmerc` file. **Q: How do I install? A: Use npm or Homebrew.
