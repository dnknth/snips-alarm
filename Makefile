BIN = $(PWD)/.venv3/bin
GETTEXT = /usr/local/opt/gettext

POT = locale/messages.pot
LOCALE = locale/de/LC_MESSAGES/messages.po


run: .venv3 $(LOCALE:.po=.mo) $(POT)
	PYTHONPATH=$(PWD)/../snips-skill:$(PWD)/../spoken_time $(BIN)/python3 action-alarm.py -v3

.venv3: requirements.txt
	[ -d $@ ] || python3 -m venv $@
	$(BIN)/pip3 install -r $<
	touch $@

messages: $(POT)

$(POT): action-alarm.py alarmclock.py alarm.py
	$(GETTEXT)/bin/xgettext -L python -o $@ $^

%.mo: %.po
	$(GETTEXT)/bin/msgfmt -o $@ $<

clean:
	rm -rf __pycache__ $(LOCALE:.po=.mo)
