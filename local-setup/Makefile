PYTHON ?= python3
STACK := $(PYTHON) stack.py
.PHONY: init doctor config start status logs smoke stop reset token test
init doctor config start status logs smoke stop token:
	$(STACK) $@ $(FLAGS)
reset:
	$(STACK) reset --confirm "$(CONFIRM)" $(FLAGS)
test:
	cd .. && $(PYTHON) -m unittest discover -s tests -p 'test_local_setup.py' -v
