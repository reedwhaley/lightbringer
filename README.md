# Lightbringer Bot

Lightbringer is a Discord bot for tournament and weekly match management.

It handles:

- Match creation for standard and CGC races
- Claiming and organizer management
- Racetime room creation and room info updates
- Google Calendar sync
- Discord scheduled event sync
- Seed timing and organizer reminders
- Daily tournament briefing posts
- SpeedGaming restream link updates
- Match completion and cancellation cleanup
- Archive posting for completed and cancelled matches

## What the bot does

Lightbringer is built to reduce manual organizer work.

It creates and tracks matches, posts claim cards, opens Racetime rooms, keeps calendar and Discord events in sync, and helps tournament staff recover from organizer no shows.

The bot currently supports:

- `mpr`
- `mp2r`
- `mpcgr`

## Match types

The bot behavior is driven by the match subcategory text.

### Tournament matches

If the subcategory contains `Tournament`, the bot treats it as a tournament match.

Tournament features include:

- Claim and manage flow on the claim card
- Organizer takeover and unclaim options
- Tournament reminder behavior
- Daily tournament briefing posts
- Ranked Racetime rooms
- Archive posting for completed and cancelled matches

### Weekly matches

If the subcategory contains `Weekly`, the bot treats it as a weekly.

Weekly features include:

- Weekly organizer permissions
- Weekly channel routing
- Weekly role pings
- Ranked Racetime rooms

## Permissions

### Tournament participants

Tournament participants can:

- Create or schedule tournament matches
- Create or schedule tournament CGC matches
- Cancel matches they are participating in

Tournament participants cannot:

- Claim matches
- Manage organizer ownership
- Take over or unclaim matches from the claim card
- Set seeds
- Set SpeedGaming links
- Update match details unless they are also the assigned organizer or an admin
- Complete matches unless they are also the assigned organizer or an admin

### Tournament organizers

Tournament organizers can:

- Create tournament matches
- Claim tournament matches
- Use the claim card manage flow on tournament matches
- Set seeds for matches assigned to them
- Set CGC room names and passwords for matches assigned to them
- Update match information for matches assigned to them
- Cancel matches they are assigned to
- Complete matches they are assigned to
- Set SpeedGaming links for tournament matches they have access to

### Weekly organizers

Weekly organizers can:

- Create weekly matches
- Claim weekly matches
- Set seeds for weekly matches assigned to them
- Update weekly matches assigned to them
- Cancel weekly matches they are assigned to
- Complete weekly matches they are assigned to
- Set SpeedGaming links for weekly matches they have access to

### Admins

Admins can do everything.

This includes:

- Discord users with the Discord Administrator permission
- Tournament Admin role
- Server Admin role

## Time entry format

The bot accepts both of these formats for the match time field:

- `2026-04-19 12:26`
- `2026-04-19 1226`

Three digit times also work:

- `2026-04-19 926`

## Core command guide

All commands are slash commands under `/match`.

---

## `/match create`

Create a standard 1v1 match.

### Use when

Use this for normal tournament or weekly races in `mpr` or `mp2r`.

### Who can use it

- Tournament participants for tournament matches
- Tournament organizers for tournament matches
- Weekly organizers for weekly matches
- Admins

### Required fields

- `category`
- `subcategory`
- `team1`
- `team2`
- `start_local`
- `timezone_name`
- `match_name`

### Optional fields

- `team1_user`
- `team2_user`
- `notes`

### Notes

- `match_name` is required and is the main title used in events, lists, and claim cards.
- `notes` is optional and can be used for race admin notes or other internal details.

### Example

`/match create category:mpr subcategory:"Prime Tournament" team1:"Player A" team2:"Player B" start_local:"2026-04-19 1226" timezone_name:CT match_name:"Prime Round 1"`

---

## `/match create_cgc`

Create a CGC team match.

### Use when

Use this for `mpcgr` team races.

### Who can use it

- Tournament participants for tournament matches
- Tournament organizers for tournament matches
- Weekly organizers for weekly matches
- Admins

### Required fields

- `category`
- `subcategory`
- `team1`
- `team2`
- `team1_player1_user`
- `team1_player2_user`
- `team2_player1_user`
- `team2_player2_user`
- `start_local`
- `timezone_name`
- `match_name`

### Optional fields

- `notes`

### Example

`/match create_cgc category:mpcgr subcategory:"CGC Tournament" team1:"Team Orange" team2:"Team Green" team1_player1_user:@A team1_player2_user:@B team2_player1_user:@C team2_player2_user:@D start_local:"2026-04-19 1900" timezone_name:CT match_name:"CGC Quarterfinal 1"`

---

## `/match update`

Update an existing match.

### Who can use it

- Assigned organizer
- Admins

### What it can update

- `match_name`
- `team1`
- `team2`
- Standard participant Discord users
- CGC player Discord users
- `notes`

### Use when

Use this if a match name changes, participant assignments need correction, or notes need to be adjusted after creation.

### Example

`/match update match_id:MPR-ABC123 match_name:"Prime Round 1 Updated" notes:"Optional notes for match (RAs, etc) go here."`

---

## `/match assign`

Assign a match to a specific organizer.

### Who can use it

- Organizer with access to that match type
- Admins

### Use when

Use this to directly assign a match to a known organizer instead of waiting for them to claim it.

### Example

`/match assign match_id:MPR-ABC123 user:@Organizer`

---

## `/match claim`

Claim an unassigned match for yourself.

### Who can use it

- Organizer with access to that match type
- Admins

### Use when

Use this to claim an unassigned match without using the claim card button.

### Example

`/match claim match_id:MPR-ABC123`

---

## Claim card button behavior

The claim card in Discord is the primary organizer workflow.

### Unclaimed match

The card shows a blue `Claim` button.

Clicking it claims the match for the organizer who clicked it.

### Claimed tournament match

The card shows a red `Unclaim / Takeover` button.

Clicking it opens a management flow with two options:

- Take over
- Unclaim

After choosing an action, a reason is required.

Reason options:

- Assigned organizer no-show
- Personal issue
- Accidental claim
- Emergency coverage
- Other

The bot then:

- Reassigns or unclaims the match
- Updates calendar and Discord event data
- Refreshes the claim card
- Logs the action in the tournament admin channel

### Claimed non-tournament match

The card shows `Claimed`.

The tournament management flow is only enabled for tournament matches.

---

## `/match set_seed`

Set the seed permalink and hash for a match.

### Who can use it

- Assigned organizer
- Admins

### Required fields

- `match_id`
- `permalink`
- `seed_hash`

### What it does

- Saves the seed to the database
- Updates the Google Calendar event
- Updates the Discord scheduled event
- Updates the Racetime room info if the room already exists

### Example

`/match set_seed match_id:MPR-ABC123 permalink:DZgCWw8-ZEBv... seed_hash:"Caverns Boost Oculus (AJNQ6PTE)"`

---

## `/match speedgaming`

Set the SpeedGaming or restream Twitch URL for a match.

### Who can use it

- Any organizer with access to that match type
- Admins

### What it does

- Saves the restream URL
- Updates the Google Calendar event
- Updates the Discord scheduled event
- Adds the `Restream:` line in the Discord event description
- Uses the SpeedGaming link as the Discord event location when present
- Can be used even if you are not the assigned organizer, as long as you have organizer access for that match type

### Example

`/match speedgaming match_id:MPR-ABC123 url:"https://www.twitch.tv/speedgaming"`

---

## `/match password`

Set the RDV room name and password for a CGC team.

### Who can use it

- Assigned organizer
- Admins

### Only available for

- `mpcgr`

### Required fields

- `match_id`
- `team`
- `room_name`
- `password`

### What it does

- Stores the team room name and password
- Updates calendar and Discord event data
- At the correct time, the bot DMs the right team members their room details

### Example

`/match password match_id:MPCGR-ABC123 team:team1 room_name:"CGC Room A" password:"secret123"`

---

## `/match complete`

Mark a match complete.

### Who can use it

- Assigned organizer
- Admins

### What it does

- Marks the match complete
- Deletes the Discord scheduled event
- Posts a plain text archive summary into the completed matches thread
- Deletes the original claim box from the claim channel
- Cleans up runtime reminder messages

### Example

`/match complete match_id:MPR-ABC123`

---

## `/match cancel`

Cancel a match.

### Who can use it

- Assigned organizer
- Admins
- Participants in that match

### What it does

- Cancels the match
- Deletes the Google Calendar event
- Deletes the Discord scheduled event
- Posts a plain text archive summary into the cancelled matches thread
- Deletes the original claim box from the claim channel
- Cleans up runtime reminder messages
- Posts a notice to the correct reminder channel

### Example

`/match cancel match_id:MPR-ABC123`

---

## `/match list`

Show upcoming active matches.

### What it shows

- Match ID
- Match title or participant names
- Category and subcategory
- Start time
- Claimed organizer

### Example

`/match list`

---

## Automation and timing guide

## Racetime room opening

The bot opens the Racetime room 30 minutes before the race start.

## Seed prompt timing

The bot prompts for seed handling at T minus 20.

## Organizer reminder timing

There is one organizer reminder for each active match.

- Reminder time: T minus 60 from race start
- Meaning: Racetime setup opens in 30 minutes

If the match is claimed:
- The assigned organizer is pinged

If the match is unclaimed:
- The fallback staff role is pinged

## CGC password DM timing

For CGC matches, team room credentials are DMd to the correct players at the correct time once they are stored.

## Racetime room state syncing

If the Racetime room changes state, the bot syncs back to the local match.

Handled states include:

- Active race
- Complete
- Cancelled

If Racetime cancels the room:
- The bot cancels the local match
- Removes calendar and event data
- Posts an archive summary
- Deletes the claim box
- Posts a notice for staff

If Racetime finishes the room:
- The bot completes the local match
- Removes the Discord scheduled event
- Posts an archive summary
- Deletes the claim box
- Cleans up runtime messages

## Daily tournament briefing

The bot posts a tournament briefing each day at 10:00 AM Central.

### Where it posts

- Tournament staff channel

### What it includes

- One staff ping at the top
- All tournament matches for that day
- Match label
- Local time
- Claimed or unclaimed status

### Format

`Match Label || <local time> || **Claimed by @User**`

or

`Match Label || <local time> || **UNCLAIMED**`

## Archive threads

Completed and cancelled matches are archived into dedicated threads.

### Completed matches thread

Used for plain text summaries of completed matches.

### Cancelled matches thread

Used for plain text summaries of cancelled matches.

### Archive summary format

Each archive post includes:

- Match ID
- Match name
- Final state
- Event category and subcategory
- Claimed organizer as plain text
- Start time
- Racetime link
- Restream link if present

The archive summary does not ping the organizer.

## Google Calendar and Discord events

The bot keeps calendar and Discord event data in sync whenever the match changes.

This includes updates after:

- create
- assign
- claim
- takeover
- unclaim
- set_seed
- speedgaming
- password
- update
- complete
- cancel

## Recommended workflow

### Standard tournament match

1. Create the match with `/match create`
2. Organizer claims the match
3. Room opens automatically
4. Organizer sets seed with `/match set_seed`
5. If SpeedGaming assigns a restream, set it with `/match speedgaming`
6. Complete the match with `/match complete`

### CGC match

1. Create the match with `/match create_cgc`
2. Organizer claims the match
3. Room opens automatically
4. Organizer sets both team room names and passwords with `/match password`
5. Organizer sets the seed with `/match set_seed`
6. If needed, set the restream with `/match speedgaming`
7. Complete the match with `/match complete`

### Organizer no-show recovery

1. On a claimed tournament card, click `Unclaim / Takeover`
2. Choose `Take over` or `Unclaim`
3. Choose a reason
4. The bot updates the claim state and logs the action to the admin channel

## Troubleshooting

## The create command says it cannot parse time

Check:

- Date format is `YYYY-MM-DD`
- Time is either `HH:MM`, `HHMM`, or `HMM`
- Timezone is one of the supported aliases

Examples:

- `2026-04-19 12:26`
- `2026-04-19 1226`
- `2026-04-19 926`

## The claim card does not allow takeover

Takeover is only enabled for tournament matches.

The subcategory must contain `Tournament`.

## The Racetime room did not update immediately

Check:

- The category has valid Racetime client credentials
- The room was created as listed, not unlisted
- The seed or room update command completed successfully

## The Discord event looks wrong

Check:

- The match has the correct `match_name`
- The SpeedGaming link is set if you want a restream shown
- The event location uses the SpeedGaming link first when present

## Notes on naming

### `match_name`

This is the required display title for the match.

Use this for the actual public-facing match title you want shown in:

- claim cards
- Discord scheduled events
- lists
- daily briefing posts
- archive summaries

### `notes`

This is optional.

Use it for internal notes such as:

- runners agreements
- special handling notes
- staff-only reminders
