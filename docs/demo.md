# Demo walkthrough

Start with a fresh demo profile if you plan to run the exact-count verifier.
Both walkthroughs use the local access key printed by `./demo key`.

## Voice, chat, and simulated SMS

Start the stack, then open the showcase.
[Quickstart](../README.md#run-it-locally) · [Open the showcase](http://127.0.0.1:5189/channel-policy.html)

1. In **Connection setup**, enter the output of `./demo key` and select
   **Use key**. Select **Join session**. Wait for **Ready**, then select
   **Enable audio** to hear the agent.
2. In **Text**, send “Hi, can I move my booking to a later date?” Look for the
   input linked to durable work under **Current case**. The **Policy check**
   panel reads **Eligible under the policy** when the result becomes available.
3. Select **Recorded voice** and keep **Recorded clip** selected. Select
   **Enable voice input**, then **Start turn**. Let the clip play, then select
   **Commit turn**. The clip travels over the LiveKit audio track. Recognition
   uses a fixture transcript, and the agent plays a scripted reply.
4. Select **End** and wait for **Session ended**. Under **Continue by simulated
   SMS**, enter “Any update on moving my booking?” and select **Send simulated
   SMS**. Wait for the SMS receipt and a third input linked to durable work.
5. Select **Join again**. The new LiveKit room reads the same case and its
   current policy result. The tab marks earlier captions **previous session**.
   Select **End** when finished.

Browser captions and audio playback describe the media session. The work count
and policy panel come from separate durable reads. **End** closes the room and
drains its accepted input handoff while the background executor keeps running.
If a text acknowledgement is unknown, select **Retry original message** to
reconcile the same input.

## Exact approval in the operator console

Choose **Open the operator console** on the landing page to start a separate
synthetic booking case. [Open the operator console](http://127.0.0.1:5189/operator.html)

1. Enter the output of `./demo key` and select **Use key**. Use the sample
   booking `DEMO-BK-001` and the prefilled date on a fresh profile. Check
   **Investigate this change** and select **Submit investigation**.
2. Wait for the investigation to succeed. Select **Request trusted quote**.
   Read the proposed booking, date, amount, currency, and revisions.
3. Check **I approve this exact date, price, currency and revision** and select
   **Confirm this exact quote**. Watch the stored confirmation, supplier
   outcome, and receiver delivery appear as separate observations.
4. To return after reloading or restarting the stack, save the **Original
   task** UUID, re-enter the key, and use **Load scoped case**.

The investigation authorizes a read-only supplier check. The explicit quote
confirmation authorizes the synthetic booking change for that exact proposal.

## Verify the walkthrough

Run the verifier after ending both room sessions and observing the supplier
outcome and receiver delivery in the operator console.

```sh
./demo verify
```

The verifier reads PostgreSQL and the two synthetic SQLite ledgers. On the
fresh walkthrough it reports `case_preserved: true`, `distinct_inputs: 3`,
`closed_rooms: 2`, `delegated_results_delivered: 3`, `supplier_effects: 1`, and
`completion_receipts: 1`. The verifier also prints an `identity_digest` for the
persisted records. After `./demo down` and `./demo up`, running the same check
should report the same digest. The counts describe this fixture sequence and
extra turns or bookings will change them.

## Local lifecycle

| Command | What it does |
| --- | --- |
| `./demo up` | Builds or starts the demo and prepares fresh storage when needed. An existing demo keeps its state. |
| `./demo status` | Shows the state of the demo containers. |
| `./demo logs` | Shows recent logs from the demo containers. |
| `./demo verify` | Reconciles persisted records after both fresh walkthroughs. |
| `./demo key` | Prints the local browser access key. Keep it out of shared logs and recordings. |
| `./demo down` | Stops the demo and retains its persisted data. |
| `./demo reset --yes` | Removes this demo’s persisted data. Run `./demo up` to start fresh. |

Use `./demo key` again if you reload the page and lose browser authorization.
If audio is silent, select **Enable audio** after joining and check the browser’s
output device. The showcase profile holds sixteen inputs. Use the reset command
when you want a fresh case or have filled the profile.

## Record a fresh walkthrough

Start the stack with a fresh demo profile. On the recording host, use the
pinned Node version, Corepack, and FFmpeg. The script captures Chromium's
screen and LiveKit audio, with captions that identify scripted recognition and
simulated SMS. It reads the key directly from `./demo key` and masks credential
entry in the recording. [Node version](../.node-version)

The caller and agent clips use different voices generated offline with Kokoro.
The local stack plays the pinned audio fixtures over LiveKit. The published
video adds narration during transitions and retains the call audio from the
browser capture. [Audio fixture manifest](../services/channel_policy_demo/assets/fixtures/manifest.json) · [Kokoro model](https://huggingface.co/hexgrad/Kokoro-82M)

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm --filter @livekit-ecosystem/local-console exec playwright install chromium
node apps/local-console/scripts/record-channel-policy-demo.mjs .local/recording
./demo verify
```

The private recording directory contains `demo.mp4`, a poster, and the raw
capture and timing files. Use `FFMPEG` to point to an executable outside the
shell path.
