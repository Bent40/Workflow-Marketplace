# Quickstart: Send Your First Message

## What You'll Need

- An API key from the dashboard
- curl or any HTTP client

## 1. Set your key

```
export NOTIFY_KEY=sk_...
```

## 2. Send a message

```
curl -X POST https://api.notify.dev/v1/send \
  -H "Authorization: Bearer $NOTIFY_KEY" \
  -d '{"to":"+15551234567","body":"Hello"}'
```

## 3. Confirm delivery

A successful call returns `{"status":"queued"}`. Check the dashboard's Logs page to confirm delivery.

## Next Steps

Read the Webhooks guide to receive delivery receipts.
