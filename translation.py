from datetime import datetime
import gettext, locale, os


TRANSLATION = gettext.translation( 'messages',
    localedir=os.path.join( os.path.dirname( __file__), 'locale'))


# Install translation functions
_  = TRANSLATION.gettext
ngettext = TRANSLATION.ngettext


# Get localized day & month names
locale.resetlocale() # Duh. Why is this needed?
DAY_NAMES = [ locale.nl_langinfo( day) for day in range( locale.DAY_1, locale.DAY_7 + 1) ]
DAY_NAMES = DAY_NAMES[1:] + [DAY_NAMES[-1]]
MONTH_NAMES = [ locale.nl_langinfo( mon) for mon in range( locale.MON_1, locale.MON_12 + 1) ]


def say_time( time=None):
    "Read the time"
    
    if not time: time = datetime.now()
    hour = ngettext( "one o'clock", "{hour} o'clock",
        time.hour).format( hour=time.hour)
    minute = ngettext( '{min} minute', '{min} minutes',
        time.minute).format( min=time.minute)
    
    # gap correction in sentence
    if time.minute == 0: return hour
    return _("{minute} past {hour}").format( **locals())


def truncate_datetime( d=None, precision=60):
    'Reduce a time stamp to given precision in seconds'
    
    if not d: d = datetime.now()
    return datetime( d.year, d.month, d.day, d.hour, d.minute,
        d.second // precision * precision)


def humanize( time, only_days=False):
    "Describe the time span until a given time in human-understandable words"
    
    now = truncate_datetime()
    delta_days    = (time - now).days
    delta_hours   = (time - now).seconds // 3600
    delta_minutes = ((time - now).seconds % 3600) // 60
    
    if delta_days == 0 and not only_days:
        hours = ngettext( "one hour", "one {hours}",
            delta_hours).format( hours=delta_hours)
        minutes = ngettext( "one minute", "{min} minutes",
            delta_minutes).format( min=delta_minutes)
        
        if not delta_hours and not delta_minutes: return _('now')
        if not delta_hours:
            return _("in {minutes}").format( minutes=minutes)
        if not delta_minutes:
            return _("in {hours}").format( hours=hours)
        return _("in {hours} and {minutes}").format(
            hours=hours, minutes=minutes)
        
    if delta_days <= -2:
        return _("{day_offset} days ago").format( day_offset=delta_days)
    if delta_days == -1 and time.date() == now.date():
        delta_hours = (now - time).seconds // 3600
        return _("{hours} hours ago").format( hours=delta_hours)
    if delta_days == -1 and (time.date() - now.date()).days == -1:
        return _("yesterday")
    
    if delta_days == 0: return _("today")
    if delta_days == 1: return _("tomorrow")
    if delta_days == 2: return _("the day after tomorrow")
    
    alarm_weekday = DAY_NAMES[ time.weekday()]
    if delta_days <= 6:
        return _("on {weekday}").format( weekday=alarm_weekday)
    if delta_days == 7:
        return _("on {weekday} next week").format(
            weekday=alarm_weekday)

    # FIXME pronounciation mistakes in translation
    return _("on {weekday}, the {day}. of {month}").format(
                weekday=alarm_weekday, day=time.day,
                month=MONTH_NAMES[time.month - 1])


if __name__ == '__main__': # Test code
    from datetime import timedelta
    
    now = truncate_datetime()
    
    print( DAY_NAMES[ now.weekday()])
    print( MONTH_NAMES[ now.month - 1])
    
    print( say_time( now))
    print( humanize( now + timedelta( days=14)))
    