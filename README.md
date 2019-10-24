# snips-alarm: Timers and alarms

A skill for [Snips.ai](https://snips.ai/) with a multi-room alarm clock.
This is a drop-in replacement for [MrJohnZoidberg/Snips-Wecker](https://github.com/MrJohnZoidberg/Snips-Wecker) with bug-fixes.

## Features
- Customizable (ringtone sound, volume, ringing timeout, rooms)
- Fully localized. Currently, a German translation is included. Other translations can be easily added. Contributions are appreciated. 

## Configuration

[config.ini](config.ini) contains the skill's settings. This file must exist but may be empty. 
See [config.ini.default](config.ini.default) for a list of options with default values.
The most important ones in the `[DEFAULT]` section are:

| Parameter name  | Default | Range   | Description                                     |
|-----------------|---------|---------|-------------------------------------------------|
| playback_volume  | 60      | 0 - 100 | Volume of the ringtone                          |
| playback_timeout | 30     | > 0      | Time in seconds until ringing stops             |
| playback_alarm_wav   | resources/alarm-sound.wav |   | Path to a WAV ring tone file        |

Options in the `[DEFAULT]` section are used across all sites, unless they are
overridden in a site specific section. Sensible values are used for all missing 
options.

For site-specific settings, add a section with the site name, e.g. `[bedroom]`
and custom options. The section name must conincide with Snips' vocabulary.
If a room is unknown, you'll hear an error message with the correct room name.
For each site section, a `site_id` option is required, matching the ID
in the `bind` directive of `/etc/snips.toml` for that site.

## Usage

### Example sentences

(German examples courtesy of [Snips-Wecker](https://github.com/MrJohnZoidberg/Snips-Wecker/blob/master/README.md#1-example-sentences))

**New alarm:**

- *Wecke mich `in neun Stunden`.*
- *Kannst du mich `morgen um 8 Uhr 30` wecken?*
- *Bitte wecke mich `in drei Tagen um 5 Uhr`.*
- *Stelle einen Alarm `in zwei Minuten`.*
- *Alarmiere mich `hier` `in 15 Minuten`.*
- *Stelle im `Schlafzimmer` einen Alarm auf `10 Uhr 20`.*
- *Stelle einen Alarm in der `Küche` auf `18 Uhr 50`.*
- *Ich möchte `morgen um 7 Uhr` in `diesem Raum` geweckt werden.*
- *`Morgen` soll mich ein Wecker `um 10 Uhr` wecken.*

**Get alarms:**

- *Gibt es einen Alarm `um 12 Uhr`?*
- *Gibt es einen Wecker `um 1 Uhr` in `diesem Zimmer`?*
- *Sage alle Alarme `hier` `zwischen 21 Uhr und 23 Uhr`.*
- *Bitte zähle die Alarme von der `Küche` `bis zwanzig Uhr` auf.*
- *Wird `heute um Mitternacht` der Wecker im `Kinderzimmer` losgehen?*
- *Ist für `heute Abend neunzehn Uhr` ein Wecker aktiv?*
- *Ich will alle Alarme wissen, die `heute` in `diesem Zimmer` klingeln.*
- *Welche Alarme werden `am Mittwoch in zwei Wochen` klingeln?*

**Get next alarm:**

- *Wann klingelt in der `Küche` der nächste Alarm?*
- *Was ist der nächste Alarm?*
- *Kannst du mir sagen wann der nächste Alarm klingelt?*
- *In wie vielen Stunden klingelt `hier` der nächste Alarm?*
- *Sage mir wann der nächste Alarm klingelt.*
- *Wann ist der nächste Wecker gestellt?*
- *Wann klingelt der nächste Alarm im `Bad`?*
- *Ich will wissen wann im `Schlafzimmer` der nächste Alarm los geht.*

**Delete alarms:**

- *Lösche alle Alarme `morgen um neun Uhr` im `Foyer`.*
- *Kannst du bitte den Wecker `morgen um neun Uhr` im `Foyer` entfernen.*
- *Kannst du den Wecker `in zwei Tagen um achtzehn Uhr` im `Eingangsbereich` löschen.*
- *Alarm `um neun Uhr zehn` im `Esszimmer` löschen.*
- *Bitte den Alarm im `Wohnzimmer` `um 8 Uhr zwanzig` entfernen.*
- *Entferne den Alarm `heute um zehn Uhr` auf dem `Dachboden`.*
- *Lösche den Alarm `heute um drei Uhr` in `diesem Raum`.*
- *Entferne den Wecker im `Klo` `um acht Uhr`.*

**Get missed alarms:**

- *Habe ich Alarme `heute` `hier` verpasst?*
- *Habe ich in der Vergangenheit `hier` Alarme verpasst?*
- *Sage bitte die nicht gehörten Wecker vom `Eingang`.*
- *Kannst du die nicht gehörten Alarme sagen.*
- *Bitte lese alle verpassten Alarme von `gestern` vor.*
- *Kannst du alle verpassten Wecker von der `Küche` sagen.*
- *Sage alle verpassten Alarme von `diesem Mittwoch`.*
- *Habe ich `letzte Woche` im `Kinderzimmer` einen Alarm verpasst?*

### While ringing

You can stop an alarm with the hotword, usually "Hey Snips!".

## Translations

By default, the system language is used. For other languages,
set the `LANG` environment variable appropriately, e.g. to `fr_FR.UTF-8`.
Translation files are found in the [locale](alarmclock/locale) folder.

No programming is necessary to create a new translation:
- Get [POEdit](https://poedit.net).
- Use it to open [messages.pot](alarmclock/locale/messages.pot).
- Choose your language and translate 40-50 lines of text.
- To test, place the result in `localedir/language/LC_MESSAGES/messages.{mp}o`.
- Please share new translations. Thanks!

