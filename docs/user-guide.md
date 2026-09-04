# SCF Compliance Agent — User Guide

A short guide for people **using** the web app (not deploying it).

## 1. Where to go

Open **https://dscwjgic9km2y.cloudfront.net** in a browser.

> Deployers: the current URL is always `terraform output -raw frontend_url`.

You'll see a **"Sign in required"** screen. The app shows nothing else until you
log in.

## 2. Get an account

Accounts are created by an administrator — you can't self-register. Ask your
admin to run:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_LYSTa2sIN \
  --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL \
  --region us-east-1
```

Cognito emails you a **temporary password**. (`--desired-delivery-mediums EMAIL` is required —
the AWS CLI defaults to `SMS` if it's omitted, and since no phone number is set the invite has
nowhere to go, so no email is sent even though the user is created. If it still doesn't arrive,
check spam: this pool uses Cognito's built-in sender, not a custom SES domain.)

## 3. First sign-in

1. On the app, click **🔐 Log in**.
2. You're taken to the Amazon Cognito sign-in page.
3. Enter your **email** and the **temporary password** from the email.
4. Cognito prompts you to set a **permanent password**.
5. You're redirected back to the app, now signed in. The sidebar shows
   **"Signed in as \<your email\>"**.

Later sign-ins skip straight to step 3 (email + your permanent password).

## 4. The Chat page (default)

Ask questions about the Secure Controls Framework and compliance:

- *"Look up SCF control GOV-01 and show the evidence requirements."*
- *"What controls map to HIPAA? Show the top 10."*
- *"We have GOV-01, IAC-01, IAC-15, NET-01, CRY-01 — what are our HIPAA gaps?"*
- *"What does SCR-CMM Level 3 look like for incident response?"*
- *"How do we answer the SIG question about encryption at rest?"*

Sidebar controls:

| Control | What it does |
|---|---|
| **Quick Prompts** | One-click example questions |
| **🗑️ Clear Chat** | Start a fresh conversation (new session) |
| **💾 Export Chat as Report** | Download the conversation as a Markdown file |
| **Log out** | End your session |

Notes:

- This is a **specialist** assistant. Questions outside cybersecurity,
  governance, risk, and compliance are declined, as are attempts to make it
  ignore its instructions.
- Long, multi-part questions can take 20–40 seconds. If a request is very large,
  break it into smaller ones.
- Each browser tab is its own chat session. Closing the tab ends it.
- **Do not paste secrets, credentials, or personal data** into the chat.

## 5. The Approve Answers page (reviewers only)

Reachable from **✅ Approve Answers** in the left sidebar. This is where
questionnaire answers extracted from uploaded documents are reviewed before the
agent is allowed to reuse them.

For each **DRAFT** answer you can:

- **Edit** the answer text, then **✅ Approve** — it becomes `APPROVED` and the
  agent can cite it. Your signed-in identity is recorded as the approver
  automatically (there's no name field).
- **💾 Save Edit** — save your edits without changing the status.
- **❌ Reject** — mark it `REJECTED` (kept for the audit trail).

Use the **Status** filter in the sidebar to view DRAFT / APPROVED / REJECTED / ALL.
Every change is written to an audit log.

## 6. Signing out

Click **Log out** in the sidebar. You'll return to the "Sign in required" screen.

## 7. If something's wrong

| Symptom | What to do |
|---|---|
| Stuck on "Sign in required" after logging in | Allow cookies for `cloudfront.net`, then retry. Private/incognito windows that block third-party cookies can loop. |
| Page shows a grey "loading" placeholder and never fills in | Refresh once. If it persists, the app may be redeploying — try again in a few minutes. |
| "Sign in" fails with *user does not exist* / *account disabled* | Ask your admin to create or re-enable your account. |
| The agent replies *"I can only help with cybersecurity compliance…"* to a normal SCF question | Rephrase more specifically (name a control, domain, or framework). If it keeps happening on clearly on-topic questions, tell your admin — the content guardrail may need tuning. |
| Chat seems to "forget" earlier messages | You're in a new tab/session, or **Clear Chat** was used. History is per-session and not saved server-side. |
