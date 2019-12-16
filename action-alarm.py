#!/usr/bin/env python3

from alarmclock import AlarmClock
from snips_skill import end_on_error, end_session, log_intent, Skill


PREFIX = "dnknth:"
MQTT_CLIENT = Skill()
ALARMCLOCK = AlarmClock( MQTT_CLIENT)


def on( intent, handler):
    'Register an intent that ends the session'
    
    MQTT_CLIENT.on_intent( PREFIX + intent)(
        end_session( log_intent( handler)))


on( 'newAlarm',        ALARMCLOCK.new_alarm)
on( 'getAlarms',       ALARMCLOCK.get_alarms)
on( 'getNextAlarm',    ALARMCLOCK.get_next_alarm)
on( 'getMissedAlarms', ALARMCLOCK.get_missed_alarms)
on( 'answerAlarm',     ALARMCLOCK.answer_alarm)
on( 'confirmAlarm',    ALARMCLOCK.confirm_delete)

# Special case: This intent continues the session with custom data.
MQTT_CLIENT.on_intent( PREFIX + 'deleteAlarms')(
    end_on_error( log_intent( ALARMCLOCK.delete_alarms)))


# All intents are registered, let's go!
if __name__ == '__main__':
    ALARMCLOCK.log.setLevel( MQTT_CLIENT.log_level)
    ALARMCLOCK.alarmctl.log.setLevel( MQTT_CLIENT.log_level)
    MQTT_CLIENT.connect().loop_forever()
