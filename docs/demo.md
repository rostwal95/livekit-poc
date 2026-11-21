# Demo walkthrough

## Voice, chat, and simulated SMS

Open [the showcase](http://127.0.0.1:5189/channel-policy.html) after completing
the [quickstart](../README.md#run-it-locally).

1. In **Connection setup**, enter the output of `./demo key` and select
   **Use key**. Select **Join session**. Wait for **Ready**, then select
   **Enable audio** to hear the agent.
2. In **Text**, send “Hi, can I move my booking to a later date?” Look for the
   input linked to durable work under **Current case**. The **Policy check**
   panel reads **Eligible under the policy** when the result becomes available.
3. Select **Recorded voice** and keep **Recorded clip** selected. Select
   **Enable voice input**, then **Start turn**. Let the clip play, then select
   **Commit turn**. The recording travels over the LiveKit audio track. The
   scripted recognizer uses a fixture transcript.
4. Select **End** and wait for **Session ended**. Under **Continue by simulated
   SMS**, send “Any update on moving my booking?” The signed local simulator
   sends from a seeded sender associated with this case. Wait for the SMS
   receipt and an additional input linked to durable work.
5. Select **Join again**. The fresh LiveKit room reads the
   same case and its current policy result. In the same tab, earlier captions
   are marked **previous session**. Select **End** when finished.

Browser captions and audio playback describe the media session. The work count
and policy panel come from separate durable reads. **End** closes the room and
drains its accepted input handoff while the background executor keeps running.
If a text acknowledgement is unknown, select **Retry original message** to
reconcile the same input.

## Exact approval in the operator console

Open [the operator console](http://127.0.0.1:5189/operator.html) from the landing
page. This walkthrough uses a separate synthetic booking case.

1. Enter the output of `./demo key` and select **Use key**. Use the prefilled
   booking and choose a requested check-in date. Check **Investigate this
   change** and select **Submit investigation**.
2. Wait for the investigation to succeed. Select **Request trusted quote**.
   Read the proposed booking, date, amount, currency, and revisions.
3. Check **I approve this exact date, price, currency and revision** and select
   **Confirm this exact quote**. Watch the stored confirmation, supplier
   outcome, and receiver delivery appear as separate observations.
4. To return after reloading or restarting the stack, save the **Original
   task** UUID, re-enter the key, and use **Load scoped case**.

The investigation authorizes a read-only supplier check. The explicit quote
confirmation authorizes the synthetic booking change for that exact proposal.

## Local lifecycle

| Command | What it does |
| --- | --- |
| `./demo up` | Builds or starts the demo and prepares fresh storage when needed. An existing demo keeps its state. |
| `./demo status` | Shows the demo stack’s status. |
| `./demo verify` | Reconciles the three inputs, two rooms, three result deliveries, and booking effect and receipt after both fresh walkthroughs. |
| `./demo key` | Prints the local browser access key. Keep it out of shared logs and recordings. |
| `./demo down` | Stops the demo and retains its persisted data. |
| `./demo reset --yes` | Removes this demo’s persisted data. Run `./demo up` to start fresh. |

Use `./demo key` again if you reload the page and lose browser authorization.
If audio is silent, select **Enable audio** after joining and check the browser’s
output device. The showcase profile holds sixteen inputs. Use the reset command
when you want a fresh case or have filled the profile.

## Record a fresh walkthrough

The recorder uses Chromium and FFmpeg. It captures the application’s actual
screen and LiveKit audio, with captions that identify the scripted and simulated
parts of the demo. It reads the key directly from `./demo key` and masks
credential entry in the recording. Start with a fresh demo profile.

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm --filter @livekit-ecosystem/local-console exec playwright install chromium
node apps/local-console/scripts/record-channel-policy-demo.mjs .local/recording
./demo verify
```

The private recording directory contains `demo.mp4`, a poster, and the raw
capture and timing files. Use `FFMPEG` to point to an executable outside the
shell path.
