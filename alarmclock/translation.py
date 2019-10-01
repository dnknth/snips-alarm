# -*- coding: utf-8 -*-
import datetime, gettext, os
import arrow.locales


LANGUAGE = "de"
LOCALES = os.path.join( os.path.dirname( __file__), 'locales')
TRANSLATION = gettext.translation( 'messages', localedir=LOCALES, languages=[LANGUAGE])
_ = TRANSLATION.gettext
ngettext = TRANSLATION.ngettext


ROOM_PREPOSITIONS = {
    # Map translated room names to room names with prepositions
    # for languages that use genders for room names
    _("office"):      _("in the office"),
    _("dining room"): _("in the dining room"),
    _("bathroom"):    _("in the bathroom"),
    _("kid's room"):  _("in the kid's room"),
    _("livingroom"):  _("in the livingroom"),
    _("bedroom"):     _("in the bedroom"),
    _("kitchen"):     _("in the kitchen"),
}

# Remove captitalization in keys
ROOM_PREPOSITIONS = { k.lower(): v for k, v in ROOM_PREPOSITIONS.items() }

# This may be wrong for arbitrary rooms e.g. "on the terrace"
DEFAULT_PREPOSITION = _("in the {room}")


def preposition( room):
    return ROOM_PREPOSITIONS.get( room.lower(),
        DEFAULT_PREPOSITION.format( room=room))


def spoken_time( alarm_time):
    
    hour = ngettext( "one o'clock", "{hour} o'clock",
        alarm_time.hour).format( hour=alarm_time.hour)
    minute = ngettext( '{min} minute', '{min} minutes',
        alarm_time.minute).format( min=alarm_time.minute)
    
    # gap correction in sentence
    if alarm_time.minute == 0: return hour
    return _("{minute} past {hour}").format( **locals())


TIME_LOCALES = {
    'de': arrow.locales.DeutschBaseLocale,
    'en': arrow.locales.EnglishLocale,
    # 'es': arrow.locales.SpanishLocale,
    'fr': arrow.locales.FrenchLocale,
    'it': arrow.locales.ItalianLocale,
    'ja': arrow.locales.JapaneseLocale,
}

TIME_LOCALE = TIME_LOCALES[ LANGUAGE]

def humanize( alarm_time, only_days=False):
    now = datetime.datetime.now()
    now = datetime.datetime( now.year, now.month, now.day, now.hour, now.minute)
    
    delta_days = (alarm_time - now).days
    delta_hours = (alarm_time - now).seconds // 3600
    if (delta_days == 0 or delta_hours <= 12) and not only_days:
        delta_minutes = ((alarm_time - now).seconds % 3600) // 60
        
        hour_words = ngettext( "in one hour", "in {hours} hours", delta_hours).format(
            hours=delta_hours)
            
        minute_words = ngettext( "one minute", "{minutes} minutes", delta_minutes).format(
            minutes=delta_minutes)
        
        if not delta_hours and not delta_minutes: return _('now')
        if not delta_minutes: return hour_words
        if not delta_hours: return _("in {minutes}").format(minutes=minute_words)
        return _("{hours} and {minutes} minutes").format(
            hours=hour_words,
            minutes=minute_words)
        
    if delta_days == 0: return _("today")
    if delta_days == 1: return _("tomorrow")
    if delta_days == 2: return _("the day after tomorrow")
    if delta_days == -1 and alarm_time.date() == now.date():
        delta_hours = (now - alarm_time).seconds // 3600
        return _("{hours} hours ago").format( hours=delta_hours)
    if delta_days == -1 and (alarm_time.date() - now.date()).days == -1:
        return _("yesterday")
    if delta_days <= -2: return _("{day_offset} days ago").format( day_offset=delta_days)
    
    alarm_weekday = TIME_LOCALE.day_names[alarm_time.weekday()]
    if 3 <= delta_days <= 6: return _("on {weekday}").format( weekday=alarm_weekday)
    if delta_days == 7: return _("on {weekday} next week").format( weekday=alarm_weekday)

    return _("in {day_offset} days, on {weekday}, the {day}. {month}.").format( 
                day_offset=delta_days,
                weekday=alarm_weekday,
                day=alarm_time.day,
                month=DeutschBaseLocale.month_names[alarm_time.month])


def get_interval_part( from_time, to_time):

    to_part = ""
    from_word = _("as of")
    future_part_to = ""

    if to_time:
        from_word = _("from")
        if to_time.date() != get_now_time().date():
            future_part_to = humanize( to_time, only_days=True)
        to_part = _("to {future_part_to} {time}").format( 
                        future_part_to=future_part_to,
                        time=spoken_time(to_time))
        
    from_part = ""
    future_part_from = ""
    if from_time:
        if from_time.date() != get_now_time().date():
            future_part_from = humanize(from_time, only_days=True)

        from_part = _("{from_word} {future_part_from} {time}").format(
                         from_word=from_word,
                         future_part_from=future_part_from,
                         time=spoken_time(from_time))

    return from_part + " " + to_part
