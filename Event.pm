#----------------------------------------------------------------------------------
#----------------------------------------------------------------------------------
package Event;
#----------------------------------------------------------------------------------
#----------------------------------------------------------------------------------
use warnings;
use strict;
use IO::All;
use Ska::RDB qw(read_rdb);
use Config::General;
use Data::Dumper;
use HTML::Table;
use Ska::Convert qw(date2time time2date);
use Quat;
use Carp;
use POSIX qw(floor strftime);
use Class::MakeMethods::Standard::Hash ( 
  scalar => [ qw(date_start date_stop delta_date local_date type tstart tstop
		 target_quat maneuver load_segment) ] );

our $DateRE  = qr/\d\d\d\d:\d+:\d+:\d+:\d\d\.?\d*/;
our $CurrentTime;
1;

##***************************************************************************
sub set_CurrentTime {
##***************************************************************************
    $CurrentTime = shift;
}

##***************************************************************************
sub new {
##***************************************************************************
    my $class = shift;
    my $evt = { @_ };
    bless ($evt, $class);

    my %event_type = (#'Pass Plan'                 => 'comm_pass'   ,
		      'DSN Comm Time'             => 'comm_pass'   ,
		      'Observation'               => 'observation' ,
		      'Target Quaternion'         => 'target_quat' ,
		      'Maneuver'                  => 'maneuver'    ,
		      'Acquisition Sequence'      => 'acq_seq'     ,
		      'Radmon Processing Enable'  => 'radmon_enab' ,
		      'Radmon Processing Disable' => 'radmon_dis'  ,
		      'Sun Position Monitor Enable'   => 'sun_pos_mon_enab' ,
		      'Sun Position Monitor Disable'  => 'sun_pos_mon_dis' ,
		      'Momentum Monitor Enable'   => 'momentum_mon_enab' ,
		      'Momentum Monitor Disable'  => 'momentum_mon_dis' ,
		      'Load Uplink'               => 'load_uplink' ,
		      'Load Segment'              => 'load_segment',
                      'Target Calibration'        => 'er'          ,
		      'Violation'                 => 'violation'   ,
		      'SCS-107 (Commanded)'       => 'scs107_cmd',
		      'SCS-107 (Autonomous)'      => 'scs107_auto',
		      'SCS-107 (Detected)'        => 'scs107_det',
		      'Normal Sun Mode'           => 'normal_sun_mode',
		      'Bright Star Hold'          => 'bright_star_hold',
		      'Safe Mode'                 => 'safe_mode',
		      'Now'                       => 'now',
		      'Grating Moves'             => 'grating',
		      'SIM Translation'           => 'sim_trans',
		      'SIM Focus'                 => 'sim_focus',
		      'Eclipse'                   => 'eclipse',
		     );

    # Set up some convenient values
    $evt->{type} = $event_type{$evt->{'Type Description'}}
      or croak("Unexpected event type: " . Dumper($evt) . "\n");
    $evt->{date_start} = format_date($evt->{'TStart (GMT)'});
    $evt->{date_stop}  = format_date($evt->{'TStop (GMT)'});
    $evt->{tstart} = date2time($evt->{'date_start'}, 'unix_time');
    $evt->{tstop} = date2time($evt->{'date_stop'}, 'unix_time');
    $evt->{summary} = $evt->{'Type Description'} unless defined $evt->{summary};

    my $init = "init_" . $evt->{type};
    eval { $evt->$init };

    $evt->set_dates($CurrentTime);

    return $evt;
}

##***************************************************************************
sub get {
##***************************************************************************
    my $evt = shift;
    my $param = shift;

    return $evt->{$param};
}

##***************************************************************************
sub summary {
##***************************************************************************
    my $evt = shift;

    if ($evt->type eq 'maneuver') {
	if (defined (my $targ = $evt->target_quat)) {
	    $evt->{summary} = sprintf("Maneuver to %.5f %.5f %.3f [%s]",
				      $targ->{ra},
				      $targ->{dec},
				      $targ->{roll},
				      $evt->{date_stop},
				     );
	}
    }

    return $evt->{summary};
}

##***************************************************************************
sub obsid {
##***************************************************************************
    my $evt = shift;

    if ($evt->{type} eq 'observation') {
	return $evt->{'OBS.OBSID'};
    } elsif ($evt->{type} eq 'er') {
	return $evt->{'TARGET_CAL.OBSID'};
    }

    return;
}

##***************************************************************************
sub quat {
##***************************************************************************
    my $evt = shift;
    
    return ($evt->type eq 'target_quat') ? $evt->{quat} : undef;
}

##***************************************************************************
sub load_name {
##***************************************************************************
    my $evt = shift;

    if ($evt->{type} eq 'load_segment') {
	return $evt->{'LOADSEG.LOAD_NAME'};
    }

    return;
}



sub init_violation {
    my $evt = shift;
    $evt->{summary} = $evt->{violation};
}

sub init_grating {
    my $evt = shift;
    $evt->{summary} = "Grating: " . $evt->{'GRATING.GRATING'};
}

sub init_sim_trans {
    my $evt = shift;
    $evt->{summary} = "SIM translation to " . $evt->{'SIMTRANS.POS'};
}

sub init_sim_focus {
    my $evt = shift;
    $evt->{summary} = "SIM focus to " . $evt->{'SIMFOCUS.POS'};
}

sub init_er {
    my $evt = shift;
    $evt->{summary} = sprintf("ER Obsid: %d  (%d ksec) Purpose: %s ",
			      $evt->{'TARGET_CAL.OBSID'},
			      ($evt->{tstop} - $evt->{tstart})/1000,
			      substr($evt->{'TARGET_CAL.TARGET'}, 0, 20),
			     );
}

sub init_load_uplink {
    my $evt = shift;
    local $_;

    my $delta_date_start = calc_delta_date(date2time($evt->{'LOAD_UPLINK.loadseg_as_planned_tstart'},'unix'),
					   $CurrentTime);
    my $delta_date_stop  = calc_delta_date(date2time($evt->{'LOAD_UPLINK.loadseg_as_planned_tstop'},'unix'),
					   $CurrentTime);
    $delta_date_start =~ s/\A\s+|\s+\Z//g;
    $delta_date_stop =~ s/\A\s+|\s+\Z//g;

#    $evt->{summary} = sprintf("Uplink %s:%s (%s to %s)",
#			      $evt->{'LOAD_UPLINK.LOAD_NAME'},
#			      $evt->{'LOAD_UPLINK.NAME'},
#			      $delta_date_start,
#			      $delta_date_stop
#			     );
    $evt->{summary} = sprintf("Uplink %s:%s [%s]",
			      $evt->{'LOAD_UPLINK.LOAD_NAME'},
			      $evt->{'LOAD_UPLINK.NAME'},
			      $evt->{date_stop},
			     );
}
			      
			      
sub init_load_segment {
    my $evt = shift;
    local $_;

    my $delta_date_start = calc_delta_date(date2time($evt->{tstart},'unix'), $CurrentTime);
    my $delta_date_stop  = calc_delta_date(date2time($evt->{tstop},'unix'), $CurrentTime);
    $delta_date_start =~ s/\A\s+|\s+\Z//g;
    $delta_date_stop =~ s/\A\s+|\s+\Z//g;

    $evt->{summary} = sprintf("Load %s:%s [%s]", #  to %s)",
			      $evt->{'LOADSEG.LOAD_NAME'},
			      $evt->{'LOADSEG.NAME'},
			      $evt->{date_stop},
#			      $delta_date_start,
#			      $delta_date_stop
			     );

}
			      
			      

sub init_comm_pass {
    my $evt = shift;
    my $SEC_PER_DAY = 86400;
    local $_;
    # Change date_start, date_stop, (and tstart and tstop) to correspond to
    # BOT and EOT instead of station callup.  Some shenanigans are required
    # because the iFOT values DSN_COMM.bot/eot are just 24 hour times and
    # not a full date, so we need to worry about day rollovers.

    my %track;
    my $ifot_evt_id = 'DSN_COMM';  # or  'PASSPLAN'
    $track{start} = $evt->{"${ifot_evt_id}.bot"};
    $track{stop} = $evt->{"${ifot_evt_id}.eot"};

    # Do the actual changes
    for (qw(start stop)) {
	next unless $track{$_} =~ /\d{4}/; # IGNORE the bot or eot value if not in expected format

	my ($year, $doy, $hour, $min, $sec) = split ':', $evt->{"date_$_"};
	$hour = substr $track{$_}, 0, 2;
	$min  = substr $track{$_}, 2, 2;
	my $track_time = date2time(join(":", ($year, $doy, $hour, $min, $sec)), 'unix_time');

	# Correct for any possible day rollover in the bot/eot time specification
	if (abs(my $time_delta = $track_time - $evt->{"t$_"}) > $SEC_PER_DAY/2) {
	    $track_time += $SEC_PER_DAY * ($time_delta > 0 ? -1 : 1);
	}

	$evt->{"date_$_"} = format_date(time2date($track_time, 'unix_time'));
	$evt->{"t$_"} = $track_time;
    }

    $evt->{summary} = sprintf("Comm pass on %s (duration %s)",
			      $evt->{"${ifot_evt_id}.station"},
			      calc_delta_date($evt->{tstop}, $evt->{tstart}),
			     );
}

sub init_observation {
    my $evt = shift;
    $evt->{summary} = sprintf("Obsid: %d  SI: %s (%d ksec) Target: %s ",
			      $evt->{'OBS.OBSID'},
			      $evt->{'OBS.SI'},
			      ($evt->{tstop} - $evt->{tstart})/1000,
			      substr($evt->{'OBS.TARGET'}, 0, 15),
			     );
}

sub init_target_quat {
    my $evt = shift;
    local $_;

    my $quat = Quat->new($evt->{'TARGQUAT.Q1'},
			 $evt->{'TARGQUAT.Q2'},
			 $evt->{'TARGQUAT.Q3'},
			 $evt->{'TARGQUAT.Q4'});

    $evt->{$_} = $quat->{$_} foreach qw(ra dec roll);
    $evt->{quat} = $quat;

    $evt->{summary} = sprintf("Set target attitude to %.5f %.5f %.2f",
			      $evt->{ra}, $evt->{dec}, $evt->{roll}
			     );
}

sub init_acq_seq {
    my $evt = shift;
    $evt->{summary} = sprintf("Star acqusition sequence");
}

sub init_maneuver {
    my $evt = shift;
    $evt->{summary} = sprintf("Maneuver"); # Updated later if possible
}

sub init_radmon_enab {
    my $evt = shift;
    $evt->{summary} = sprintf("RADMON Enable");
}

sub init_radmon_dis {
    my $evt = shift;
    $evt->{summary} = sprintf("RADMON Disable");
}

sub init_sun_pos_mon_enab {
    my $evt = shift;
    $evt->{summary} = sprintf("Sun Position Monitor Enable");
}

sub init_sun_pos_mon_dis {
    my $evt = shift;
    $evt->{summary} = sprintf("Sun Position Monitor Disable");
}

sub init_momentum_mon_enab {
    my $evt = shift;
    $evt->{summary} = sprintf("Momentum Monitor Enable");
}

sub init_momentum_mon_dis {
    my $evt = shift;
    $evt->{summary} = sprintf("Momentum Monitor Disable");
}

sub init_eclipse {
    my $evt = shift;
    $evt->{summary} = sprintf("Eclipse [%s]", $evt->{date_stop});
}

##***************************************************************************
sub format_date {
# This will eventually clip off the decimal seconds
##***************************************************************************
    my $date = shift;
    $date =~ s/\.\d+\Z//;
    return $date;
}

##***************************************************************************
sub set_dates {
##***************************************************************************
    my $evt = shift;
    my $time = shift;
    
    $evt->{delta_date} = calc_delta_date($evt->{tstart}, $time);
    $evt->{local_date} = calc_local_date($evt->{tstart});
}

# Class methods
##***************************************************************************
sub calc_delta_date {
##***************************************************************************
    my $t1 = shift;
    my $t2 = shift || $CurrentTime;
    
    $t1 = date2time($t1, 'unix') if ($t1 =~ /$DateRE/);
    $t2 = date2time($t2, 'unix') if ($t2 =~ /$DateRE/);

    my $dt = abs($t1 - $t2);
    my $day  = floor($dt / (60*60*24));
    my $hour = floor(($dt - $day * 60*60*24) / (60*60));
    my $min  = floor(($dt - $day * 60*60*24 - $hour * 60*60) / 60);
    my $sign = ($t1 > $t2 or ($hour == 0 && $min == 0)) ? ' ' : '-';

    my $day_string = $day > 0 ? sprintf("%dd ", $day) : '';
    my $hourmin_string = sprintf($day > 0 ? "%02d:%02d" : "%2d:%02d", $hour, $min);
    
    return $sign . $day_string . $hourmin_string;
#    return sprintf("%12s", $sign . $day_string . $hourmin_string);
}

##***************************************************************************
sub calc_local_date {
##***************************************************************************
    my $t1 = shift;

    $t1 = date2time($t1, 'unix') if ($t1 =~ /$DateRE/);
    return strftime "%l:%M %p %a %d-%b", localtime($t1);
}
