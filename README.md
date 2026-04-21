# Lightbringer

Lightbringer is a Discord bot for match scheduling, organizer workflows, SpeedGaming coordination, crew signup handling, Racetime room automation, and event sync for Metroid Prime events.

It is built for recurring weekly races and tournament operations where staff need one bot to manage match creation, room timing, crew signups, reminders, and archival flows.

## What Lightbringer does

Lightbringer handles the day to day match workflow for tournament staff and weekly organizers.

Core capabilities include:

- Create standard 1v1 matches
- Create CGC team matches
- Assign or claim matches
- Track organizer ownership
- Open and sync Racetime rooms
- Store and reveal seeds
- Store CGC room credentials and DM them at the right time
- Track SpeedGaming episode IDs and restream links
- Post and manage commentary and tracker signup boxes
- Sync match state to Google Calendar and Discord scheduled events
- Archive completed and cancelled matches
- Report final results back to O-Lir
- Attempt automatic SpeedGaming Twitch link detection shortly before match start

## Main use cases

### Weekly operations

Use Lightbringer when you have recurring weekly races and want one command flow for creation, reminders, room opening, crew signups, and archiving.

### Tournament organizer workflow

Use Lightbringer when tournament staff need to create scheduled matches, let organizers claim or be assigned, set seeds, post crew signup boxes, and keep everything synced across Discord, Racetime, and calendar events.

### CGC team match handling

Use Lightbringer when a match needs team member assignment plus private team room names and passwords that are only sent to the correct players.

### SpeedGaming coordination

Use Lightbringer when you want to track a restream URL manually or let the bot try to detect a live SpeedGaming Twitch channel shortly before the match.

## Command groups

Lightbringer currently exposes one main command group:

- `/match`

## Match commands

### `/match create`

Create a standard 1v1 match.

Use this for:
- MPR tournament matches
- MP2R tournament matches
- Weekly single player races

Required inputs:
- `category`
- `subcategory`
- `team1`
- `team2`
- `start_local`
- `timezone_name`
- `match_name`

Optional inputs:
- `team1_user`
- `team2_user`
- `notes`

What it does:
- Creates the match in the local database
- Creates or updates the calendar event
- Creates or updates the Discord scheduled event
- Posts the claim card
- Attempts SpeedGaming match submission if entrant identities are available
- Posts the crew signup box
- Links the created match back to the matching O-Lir pairing when run inside an O-Lir scheduling thread

### `/match create_cgc`

Create a CGC team match.

Use this for:
- MPCGR team races
- Team based tournament races

Required inputs:
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

Optional inputs:
- `notes`

What it does:
- Creates the team match
- Stores team member names and Discord IDs
- Creates or updates the calendar event
- Creates or updates the Discord scheduled event
- Posts the claim card
- Attempts SpeedGaming match submission if all team identities are available
- Posts the crew signup box
- Links the created match back to O-Lir when possible

### `/match update`

Update an existing scheduled match.

Use this when:
- The visible match title changed
- Team or entrant names changed
- Player Discord assignments need correction
- Notes need updating

What it can update:
- `match_name`
- `team1`
- `team2`
- Standard entrant Discord users
- CGC player Discord users
- `notes`

Who can use it:
- The assigned organizer
- Admins

What it does:
- Saves the updates
- Refreshes calendar data
- Refreshes the Discord scheduled event
- Refreshes the claim card
- Refreshes the crew signup box

### `/match assign`

Assign a match to a specific organizer.

Use this when:
- Staff already know who should cover the match
- You do not want to wait for manual claiming

Who can use it:
- Organizers with access to that match type
- Admins

What it does:
- Assigns the organizer
- Updates the calendar event
- Updates the Discord scheduled event
- Refreshes the weekly claim card
- For tournament matches, moves the claim card into the claimed tournament matches archive thread

### `/match claim`

Claim an unassigned match for yourself.

Use this when:
- An organizer wants to take ownership of an open match

Who can use it:
- Organizers with access to that match type
- Admins

What it does:
- Assigns the match to the user who claimed it
- Updates calendar and event data
- Refreshes or relocates the claim card depending on match type

Restrictions:
- A participant in the match cannot claim that match

### `/match set_seed`

Set the seed permalink and hash for a match.

Required inputs:
- `match_id`
- `permalink`
- `seed_hash`

Who can use it:
- The assigned organizer
- Admins

What it does:
- Saves the seed
- Updates the calendar event
- Updates the Discord scheduled event
- Updates Racetime room info if the room already exists

### `/match speedgaming`

Set the SpeedGaming or restream Twitch URL for a match.

Required inputs:
- `match_id`
- `url`

Who can use it:
- Organizers with access to that match type
- Admins

What it does:
- Stores the restream URL
- Updates the calendar event
- Updates the Discord scheduled event
- Refreshes related match displays

### `/match password`

Set the RDV room name and password for one CGC team.

Required inputs:
- `match_id`
- `team`
- `room_name`
- `password`

Who can use it:
- The assigned organizer
- Admins

Only valid for:
- `mpcgr`

What it does:
- Stores the private room name and password for the selected team
- Updates calendar and event data
- Later DMs the correct team members with their room credentials

### `/match complete`

Mark a match complete.

Who can use it:
- The assigned organizer
- Admins

What it does:
- Marks the match complete
- Updates the calendar event
- Deletes the Discord scheduled event
- Archives the completed match summary
- Archives the completed comms summary
- Deletes the claim box
- Deletes the crew signup box
- Cleans up tracked reminder messages

### `/match cancel`

Cancel a match.

Who can use it:
- The assigned organizer
- Admins
- Participants in that match

What it does:
- Deletes the calendar event
- Deletes the Discord scheduled event
- Marks the match cancelled
- Archives the cancelled match summary
- Deletes the claim box
- Deletes the crew signup box
- Cleans up tracked reminder messages
- Posts a staff facing notice with SpeedGaming episode information when available

### `/match list`

List active upcoming matches.

What it shows:
- Match ID
- Match title or player names
- Category and subcategory
- Scheduled time
- Assigned organizer

## Crew signup workflow

Lightbringer posts crew signup boxes for commentary and trackers.

### Signup behavior

Each signup box supports:
- Comms signups
- Tracker signups

What it stores:
- Display name
- Twitch name
- Discord username snapshot

What it also does:
- Attempts to submit the signup to the appropriate SpeedGaming volunteer page when an SG episode ID exists
- Prevents local signup storage if the SG submission fails
- Allows users to retry if the external signup fails

### Signup links

If an SG episode ID is known, the embed shows:
- The commentator signup URL
- The tracker signup URL

## Automation and timing

### Racetime room opening

The bot opens Racetime rooms automatically when the room open time is reached.

### Seed prompt timing

The bot sends seed prompts at T minus 20 when seed entry is still pending.

### Organizer reminder timing

The bot sends a reminder at T minus 60 from match start.

If the match is assigned:
- The assigned organizer is pinged

If the match is unassigned:
- The fallback staff role is pinged

### CGC password delivery

For CGC matches, team room credentials are DMd to the correct players once seed room info is ready.

### Racetime room state sync

The bot polls Racetime and reacts to these remote states:
- In progress
- Finished
- Cancelled

Effects include:
- Marking a match active
- Marking a match complete
- Cancelling a match
- Reporting results to O-Lir
- Cleaning up runtime messages

### Daily tournament briefing

The bot posts a daily briefing listing tournament matches for that day.

### Automatic SpeedGaming link scan

Roughly five minutes before match start, the bot can scan the public SpeedGaming Twitch channels and try to detect which channel is carrying the scheduled match.

If exactly one strong match is found:
- The bot stores the Twitch URL as the restream link
- Updates the calendar event
- Updates the Discord scheduled event

If no clear match is found:
- The bot does nothing

If more than one possible match is found:
- The bot does nothing rather than guessing

## O-Lir integration

Lightbringer integrates with O-Lir for identity lookups, pairing linking, and result reporting.

What it does:
- Reads SpeedGaming identity data from O-Lir
- Reads entrant identity data from O-Lir
- Links created matches back to O-Lir pairing records
- Reports completed match results back to O-Lir

This allows O-Lir to remain the tournament bracket and pairing system while Lightbringer handles live scheduling and match execution.

## Roles and permissions

Lightbringer supports several access patterns.

### Admin level access

Admins can:
- Create matches
- Update matches
- Assign matches
- Set seeds
- Complete matches
- Cancel matches
- Override normal organizer restrictions

### Organizer access

Organizers can:
- Claim or be assigned matches
- Manage matches for categories they are allowed to handle
- Set seeds
- Set SpeedGaming links
- Set CGC team credentials when assigned

### Participant restrictions

Participants may:
- Create matches if granted tournament participant role access
- Cancel matches they are part of

Participants may not:
- Claim matches they are part of

## Data and sync targets

Lightbringer keeps match information in sync across:
- SQLite or the configured database
- Google Calendar
- Discord scheduled events
- Discord claim and signup messages
- Racetime room state
- O-Lir result and pairing linkage
- SpeedGaming match and volunteer workflows

## Recommended workflows

### Standard tournament match

1. Create the match with `/match create`
2. Organizer claims or is assigned the match
3. Racetime room opens automatically
4. Organizer sets the seed with `/match set_seed`
5. If a restream is assigned, set it with `/match speedgaming` or let the Twitch scan find it
6. Mark the match complete with `/match complete`

### CGC team match

1. Create the match with `/match create_cgc`
2. Organizer claims or is assigned the match
3. Store both team room credentials with `/match password`
4. Set the seed with `/match set_seed`
5. Set the restream URL if needed
6. Complete the match with `/match complete`

### Weekly match flow

1. Create the weekly match
2. Organizer claim happens through the weekly claim workflow
3. Weekly room opens automatically
4. Crew signups collect comms and trackers
5. Match finishes and gets archived into weekly archive threads

## Environment notes

This bot expects environment variables for:
- Discord credentials
- Racetime category credentials
- Google Calendar credentials
- O-Lir API access
- SpeedGaming settings
- Twitch API access if automatic restream scanning is enabled

## Repository purpose

This repository is for the operational bot that runs live match handling.

If O-Lir is the tournament brain, Lightbringer is the scheduling and execution layer.
