# Set the task name
TASK = arc

# Uncomment the correct choice indicating either SKA or TST flight environment
FLIGHT_ENV = SKA

# Set the names of all files that get installed
#  Examples for celmon
#  TASK = celmon
#  BIN = celmon.pl 
#  SHARE = calc_offset.pl
#  DATA = CELMON_table.rdb ICRS_tables
BIN = get_iFOT_events.pl get_web_content.pl arc.pl 
SHARE = Event.pm Snap.pm parse_cm_file.pl arc_time_machine.pl get_hrc.py plot_hrc.py get_ace.py
DATA = iFOT_queries.cfg arc*.cfg web_content.cfg \
	title_image.png \
	blue_paper.gif \
	blue_paper_test.gif \
	alert_limits.html \
	task_schedule.cfg
DOC = 

# include /proj/sot/ska/include/Makefile.FLIGHT
include /proj/sot/ska/include/Makefile.FLIGHT

# Define outside data and bin dependencies required for testing,
# i.e. all tools and data required by the task which are NOT 
# created by or internal to the task itself.  These will be copied
# from the ROOT_FLIGHT area.
#
# TEST_DEP = bin/skycoor data/EPHEM/gephem.dat
TEST_DEP = data/arc/

# To 'test', first check that the INSTALL root is not the same as the FLIGHT root
# with 'check_install' (defined in Makefile.FLIGHT).  Typically this means doing
#  setenv TST $PWD
# Then copy any outside data or bin dependencies into local directory via
# dependency rules defined in Makefile.FLIGHT

# Testing no long creates a lib/perl link, since Perl should find the library
# because perlska puts /proj/sot/ska/lib/perl (hardwired) into PERL5LIB.

.PHONY: test test_char test_get test_scs107 t_scs107 test_current t_current clean t_now t_arcx

test: test_now

test_now: t_now check_install $(BIN) install $(TEST_DEP)
	$(INSTALL_BIN)/get_iFOT_events.pl
	$(INSTALL_BIN)/get_web_content.pl
	$(INSTALL_BIN)/arc.pl
	$(INSTALL_BIN)/arc.pl -config arc:arc_ops:arc_test

test_hrc: t_now check_install $(BIN) install $(TEST_DEP)
	$(INSTALL_SHARE)/get_hrc.py --h5=$(INSTALL_DATA)/hrc_shield.h5
	$(INSTALL_SHARE)/plot_hrc.py --h5=$(INSTALL_DATA)/hrc_shield.h5 --out=$(SKA)/www/ASPECT/arc/hrc_shield.png
	$(INSTALL_BIN)/arc.pl -config arc:arc_test

test_arc: t_now check_install $(BIN) install $(TEST_DEP)
	$(INSTALL_BIN)/arc.pl

test_get: check_install $(BIN) install $(TEST_DEP)
	$(INSTALL_BIN)/get_iFOT_events.pl

test_scs107: t_scs107 check_install $(BIN) install $(TEST_DEP) data/snapshot/
	$(INSTALL_BIN)/get_web_content.pl 2005:134:18:30:30
	$(INSTALL_BIN)/arc.pl 2005:134:18:30:30
	$(INSTALL_BIN)/arc.pl -config arc:arc_ops:arc_test  2005:134:18:30:30

test_get_web: check_install $(BIN) install $(TEST_DEP)
	$(INSTALL_BIN)/get_web_content.pl

t_scs107:
	if [ ! -d t_scs107 ] ; then gtar zxvf t_scs107.tgz ; fi
	if [ -r t ] ; then rm t ; fi
	ln -s t_scs107 t

test_trouble: t_trouble check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_BIN)/get_web_content.pl
	$(INSTALL_BIN)/arc.pl 2005:151:12:03:18

t_trouble:
	if [ ! -d t_trouble ] ; then gtar zxvf t_trouble.tgz ; fi
	if [ -r t ] ; then rm t ; fi
	ln -s t_trouble t

t_now:
	if [ ! -d t_now ] ; then gtar zxvf t_now.tgz ; fi
	if [ -r t ] ; then rm t ; fi
	ln -s t_now t

# Install to run in test area (typically /proj/sot/ska/test) and write to
# $WWW/arcx
installx: t_arcx check_install $(BIN) install $(TEST_DEP)

t_arcx:
	if [ -r t ] ; then rm t ; fi
	ln -s t_arcx t

install:
#  Uncomment the lines which apply for this task
	mkdir -p $(INSTALL_BIN)
	mkdir -p $(INSTALL_DATA)
	mkdir -p $(INSTALL_SHARE)
#	mkdir -p $(INSTALL_DOC)
#	mkdir -p $(INSTALL_LIB)
	rsync --times --cvs-exclude $(BIN) $(INSTALL_BIN)/
	rsync --times --cvs-exclude $(DATA) $(INSTALL_DATA)/
	rsync --times --cvs-exclude $(SHARE) $(INSTALL_SHARE)/
#	rsync --times --cvs-exclude $(DOC) $(INSTALL_DOC)/
#	rsync --times --cvs-exclude $(LIB) $(INSTALL_LIB)/
#	pod2html task.pl > $(INSTALL_DOC)/doc.html

clean:
	rm -rf bin data

