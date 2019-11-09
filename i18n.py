import gettext, locale, os
import snips_skill, spoken_time


# Install translations
LANGUAGE, ENCODING = locale.getlocale()
TRANSLATION = gettext.translation( 'messages', 
    languages=[LANGUAGE], fallback=True,
    localedir=os.path.join( os.path.dirname( __file__), 'locale'))
_  = TRANSLATION.gettext
ngettext = TRANSLATION.ngettext

snips_skill.use_language( LANGUAGE)
spoken_time.use_language( LANGUAGE)
