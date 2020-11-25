# Set the task name
TASK = arc3

FLIGHT_ENV = SKA

# Set the names of all files that get installed
SHARE = Event.pm Snap.pm parse_cm_file.pl arc_time_machine.pl \
        get_hrc.py plot_hrc.py get_ace.py get_goes_x.py plot_goes_x.py \
	make_timeline.py calc_fluence_dist.py \
        get_iFOT_events.pl get_web_content.pl arc.pl \
        iFOT_queries.cfg arc3.cfg arc_test.cfg arc_ops.cfg web_content.cfg \
	title_image.png \
	blue_paper.gif \
	blue_paper_test.gif \
	alert_limits.html \
	timeline.js timeline.css vert_line.gif \
	task_schedule.cfg

DATA =
DOC =

include /proj/sot/ska/include/Makefile.FLIGHT

# Define outside data and bin dependencies required for testing,
#
TEST_DEP = data/arc3/

.PHONY: test test_char test_get test_scs107 t_scs107 test_current t_current clean t_now t_arcx

# To 'test' get into a development Ska environment and "make test".  Most
# likely this means using /proj/sot/ska/dev the test SKA root.  This has been
# set up with a link from:
#   /proj/sot/ska/dev/www/ASPECT/arc -> /proj/sot/ska/www/ASPECT/arc/dev
# This way the test version goes live to
#   http://cxc.harvard.edu/mta/ASPECT/arc/dev/

#test: test_now
#
#test_now: check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_BIN)/get_iFOT_events.pl
#	$(INSTALL_BIN)/get_web_content.pl
#	$(INSTALL_BIN)/arc.pl -config arc:arc_test
#	$(INSTALL_BIN)/arc.pl -config arc:arc_ops
#
#test_timeline: t_now check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_SHARE)/make_timeline.py --data-dir=$(INSTALL_DATA)/
#	$(INSTALL_BIN)/arc.pl -config arc:arc_test
#
#test_ace: t_now check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_SHARE)/get_ace.py --h5=$(INSTALL_DATA)/ACE.h5
#
#test_hrc: t_now check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_SHARE)/get_hrc.py --data-dir=$(INSTALL_DATA)/
#	$(INSTALL_SHARE)/plot_hrc.py --h5=$(INSTALL_DATA)/hrc_shield.h5 --out=$(SKA)/www/ASPECT/arc/hrc_shield.png
#	$(INSTALL_BIN)/arc.pl -config arc:arc_test
#
#test_arc: t_now check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_BIN)/arc.pl
#
#test_get: check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_BIN)/get_iFOT_events.pl
#
#test_scs107: t_scs107 check_install $(BIN) install $(TEST_DEP) data/snapshot/
#	$(INSTALL_BIN)/get_web_content.pl 2005:134:18:30:30
#	$(INSTALL_BIN)/arc.pl 2005:134:18:30:30
#	$(INSTALL_BIN)/arc.pl -config arc:arc_ops:arc_test  2005:134:18:30:30
#
#test_get_web: check_install $(BIN) install $(TEST_DEP)
#	$(INSTALL_BIN)/get_web_content.pl
#
#t_scs107:
#	if [ ! -d t_scs107 ] ; then gtar zxvf t_scs107.tgz ; fi
#	if [ -r t ] ; then rm t ; fi
#	ln -s t_scs107 t
#
#test_trouble: t_trouble check_install $(BIN) install $(TEST_DEP)
##	$(INSTALL_BIN)/get_web_content.pl
#	$(INSTALL_BIN)/arc.pl 2005:151:12:03:18
#
#t_trouble:
#	if [ ! -d t_trouble ] ; then gtar zxvf t_trouble.tgz ; fi
#	if [ -r t ] ; then rm t ; fi
#	ln -s t_trouble t
#
#t_now:
#	if [ ! -d t_now ] ; then gtar zxvf t_now.tgz ; fi
#	if [ -r t ] ; then rm t ; fi
#	ln -s t_now t
#
## Install to run in test area (typically /proj/sot/ska/test) and write to
## $WWW/arcx
#installx: t_arcx check_install $(BIN) install $(TEST_DEP)
#
#t_arcx:
#	if [ -r t ] ; then rm t ; fi
#	ln -s t_arcx t
#
install:
#  Uncomment the lines which apply for this task
#	mkdir -p $(INSTALL_BIN)
	mkdir -p $(INSTALL_DATA)
	mkdir -p $(INSTALL_SHARE)
#	mkdir -p $(INSTALL_DOC)
#	mkdir -p $(INSTALL_LIB)
#	rsync --times --cvs-exclude $(BIN) $(INSTALL_BIN)/
	rsync --times --cvs-exclude $(DATA) $(INSTALL_DATA)/
	rsync --times --cvs-exclude $(SHARE) $(INSTALL_SHARE)/
#	rsync --times --cvs-exclude $(DOC) $(INSTALL_DOC)/
#	rsync --times --cvs-exclude $(LIB) $(INSTALL_LIB)/
#	pod2html task.pl > $(INSTALL_DOC)/doc.html

#clean:
#	rm -rf bin data
