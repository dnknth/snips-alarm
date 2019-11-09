# snips-alarm: Timers and alarms

A skill for [Snips.ai](https://snips.ai/) with a multi-room alarm clock.
This is a complete re-write of [MrJohnZoidberg/Snips-Wecker](https://github.com/MrJohnZoidberg/Snips-Wecker) with bug-fixes.

## Features
- Customizable (ringtone sound, volume, ringing timeout)
- Multi-room capable:
- Fully localized. Currently, a German translation is included. Other translations can be easily added without programming. Contributions are welcome. See below.

## Configuration

[config.ini](config.ini) contains the skill's settings. This file must exist but may be empty. 
See [config.ini.default](config.ini.default) for a list of options with default values.
The most important ones in the `[DEFAULT]` section are:

| Parameter name  | Default | Range   | Description                                     |
|-----------------|---------|---------|-------------------------------------------------|
| playback_volume  | 60      | 0 - 100 | Volume of the ringtone                          |
| playback_timeout | 30     | > 0      | Time in seconds until ringing stops             |
| playback_alarm_wav   | resources/alarm-sound.wav |   | Path to a WAV ring tone file        |

Options in the `[DEFAULT]` section are used across all rooms, unless they are
overridden in a site / room specific section. Sensible values are used for all missing 
options.

For room-specific settings, add a section with the site name, e.g. `[bedroom]`
and custom options. The section name must conincide with Snips' vocabulary.
If a room is unknown, you'll hear an error message with the known room name.
For each site section, a `site_id` option is required, matching the ID
in the `bind` directive of `/etc/snips.toml` for that site.

## Usage

(For German example sentences, see [Snips-Wecker](https://github.com/MrJohnZoidberg/Snips-Wecker/blob/master/README.md#1-example-sentences)). 

### While ringing

You can stop an alarm by saying the hotword, usually "Hey Snips!".
This may not work if the ringing volume is too loud.

## Translations

By default, the system language is used. For other languages,
set the `LANG` environment variable appropriately, e.g. to `fr_FR.UTF-8`.
An easy way to do this is starting `snips-skill-server` with a `LANG` setting.
 
Translation files are found in the [locale](alarmclock/locale) folder.

No programming is necessary to create a new translation:
- Get [POEdit](https://poedit.net).
- Use it to open [messages.pot](alarmclock/locale/messages.pot).
- Choose your language and translate 30-40 lines of text.
- To test, place the result in `localedir/language/LC_MESSAGES/messages.po`.
- Please share new translations. Thanks!
