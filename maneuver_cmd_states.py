import numpy as np
import asciitable

from Chandra.Time import DateTime
from Ska.DBI import DBI

dbh = DBI(dbi='sybase', server='sybase', user='aca_read')

runtime = DateTime()
daysback = 3
starttime = runtime - daysback

exclude = ['obsid', 'power_cmd', 'si_mode',
           'vid_board', 'clocking', 'fep_count', 'ccd_count', 
           'simpos', 'simfa_pos', 'pitch', 'ra', 'dec', 'roll', 
           'q1', 'q2', 'q3', 'q4', 'letg', 'hetg', 'dither', 'trans_keys']


dtype = [('Type Description', '|S20'),
         ('TStart (GMT)', '|S21'),
         ('TStop (GMT)', '|S21'),
         ('TARGQUAT.Q1', '<f4'),
         ('TARGQUAT.Q2', '<f4'),
         ('TARGQUAT.Q3', '<f4'),
         ('TARGQUAT.Q4', '<f4')]

mp_targquat = dbh.fetchall("select * from cmds "
                           "where date > '%s' " 
                           "and cmd = 'MP_TARGQUAT'" % starttime.date)

targets = []
for targ in mp_targquat:
    quat = {}
    for qid in (1,2,3,4):
        q = dbh.fetchone("select * from cmd_fltpars where cmd_id = %d " 
                         "and name = 'Q%d'" % (targ['id'], qid))
        quat[qid] = q['value']
    target = ('Target Quaternion', targ['date'], targ['date'],
              quat[1], quat[2], quat[3], quat[4])
    targets.append(target)

import Chandra.cmd_states
cmds = Chandra.cmd_states.get_cmds(datestart=starttime.date, db=dbh)
state0 = Chandra.cmd_states.get_state0(date=starttime.date, date_margin=0, db=dbh)
states = Chandra.cmd_states.get_states(state0, cmds, exclude=exclude)
manvrs = states[states['pcad_mode'] == 'NMAN']

for manvr in manvrs:
    man = ('Maneuver', manvr['datestart'], manvr['datestop'],
           None, None, None, None)
    targets.append(man)
    acq_stop = DateTime(DateTime(manvr['datestop']).secs + 4.5*60).date
    acq = ('Acquisition Sequence', manvr['datestop'], acq_stop,
           None, None, None, None)
    targets.append(acq)

table = np.rec.fromrecords(targets, dtype=dtype)
table = np.sort(table, order='TStart (GMT)')
out = open("%s.rdb" % runtime.date, 'w')
asciitable.write(table, out, Writer=asciitable.Rdb, fill_values=[('nan'), ('')])
    


