package Parse_CM_File;

###############################################################
#
# Parse one of several types of files produced in OFLS 
# command management
#
###############################################################

use POSIX;
use lib '/proj/sot/ska/lib/site_perl';
use Ska::Convert qw(date2time time2date);

use Time::JulianDay;
use Time::DayOfYear;
use Time::Local;
use IO::File;
use Carp;

$VERSION = '$Id: parse_cm_file.pl,v 1.1 2005-11-04 22:59:58 aldcroft Exp $';  # '
1;

###############################################################
sub backstop {
###############################################################
    $backstop = shift;

    @bs = ();
    open (BACKSTOP, $backstop) || confess "Couldn't open backstop file $backstop for reading\n";
    while (<BACKSTOP>) {
	my ($date, $vcdu, $cmd, $params) = split '\s*\|\s*', $_;
	$vcdu =~ s/ +.*//; # Get rid of second field in vcdu
	push @bs, { date => $date,
		    vcdu => $vcdu,
		    cmd  => $cmd,
		    params => $params,
		    time => date2time($date) };
    }
    close BACKSTOP;

    return @bs;
}

###############################################################
sub DOT {
###############################################################
    $dot_file = shift;

    # Break DOT down into commands, each with a unique ID (with index)

    undef %command;
    undef %index;
    undef %dot;

    open (DOT, $dot_file) || confess "Couldn't open DOT file $dot_file\n";
    while (<DOT>) {
	chomp;
	next unless (/\S/);
	($cmd, $id) = /(.+) +(\S+)....$/;
	$index{$id} = "0001" unless (exists $index{$id});
	$cmd =~ s/\s+$//;
	$command{"$id$index{$id}"} .= $cmd;
	$index{$id} = sprintf("%04d", $index{$id}+1) unless ($cmd =~ /,$/);
    }
    close DOT;

    foreach (keys %command) {
	%{$dot{$_}} = parse_params($command{$_});
	$dot{$_}{time}  = date2time($dot{$_}{TIME})     if ($dot{$_}{TIME});
	$dot{$_}{time} += date2time($dot{$_}{MANSTART}) if ($dot{$_}{TIME} && $dot{$_}{MANSTART});
	$dot{$_}{cmd_identifier} = "$dot{$_}{anon_param1}_$dot{$_}{anon_param2}"
	    if ($dot{$_}{anon_param1} and $dot{$_}{anon_param2});
    } 
    return %dot;
}

###############################################################
sub OR {
###############################################################
    $or_file = shift;

    open (OR, $or_file) || confess "Couldn't open OR file $or_file\n";
    while (<OR>) {
	chomp;
	if ($in_obs_statement) {
	    $obs .= $_;
	    unless (/,\s*$/) {
		%obs = OR_parse_obs($obs);
		$or{$obs{obsid}} = { %obs };
		$in_obs_statement = 0;
		$obs = '';
	    }
	}
	$in_obs_statement = 1 if (/^\s*OBS,\s*$/);
    }
    close OR;
    return %or;
 }

###############################################################
sub OR_parse_obs {
###############################################################
    $_ = shift;

    my @obs_columns = qw(obsid TARGET_RA TARGET_DEC TARGET_NAME
			 SI TARGET_OFFSET_Y TARGET_OFFSET_Z
			 SIM_OFFSET_X SIM_OFFSET_Z GRATING MON_RA MON_DEC SS_OBJECT);
    # Init some defaults
    my %obs = ();
    foreach (@obs_columns) {
	$obs{$_} = '';
    }
    ($obs{TARGET_RA}, $obs{TARGET_DEC}) = (0.0, 0.0);
    ($obs{TARGET_OFFSET_Y}, $obs{TARGET_OFFSET_Z}) = (0.0, 0.0);
    ($obs{SIM_OFFSET_X}, $obs{SIM_OFFSET_Z}) = (0, 0);

    $obs{obsid} = 0+$1 if (/ID=(\d+),/);
    ($obs{TARGET_RA}, $obs{TARGET_DEC}) = ($1, $2)
	if (/TARGET=\(([^,]+),([^,\)]+)/);
    ($obs{MON_RA}, $obs{MON_DEC}) = ($1, $2)
	if (/STAR=\(([^,]+),([^,\)]+)/);
    $obs{TARGET_NAME} = $3
	if (/TARGET=\(([^,]+),([^,]+),\s*\{([^\}]+)\}\),/);
    $obs{SS_OBJECT} = $1 if (/SS_OBJECT=([^,\)]+)/);
    $obs{SI} = $1 if (/SI=([^,]+)/);
    ($obs{TARGET_OFFSET_Y}, $obs{TARGET_OFFSET_Z}) = ($1, $2)
	if (/TARGET_OFFSET=\(([^,]+),([^,]+)\)/);
    ($obs{DITHER_ON},
     $obs{DITHER_Y_AMP},$obs{DITHER_Y_FREQ}, $obs{DITHER_Y_PHASE},
     $obs{DITHER_Z_AMP},$obs{DITHER_Z_FREQ}, $obs{DITHER_Z_PHASE}) = split ',', $1
	 if (/DITHER=\(([^)]+)\)/);
    $obs{SIM_OFFSET_Z} = $1
	if (/SIM_OFFSET=\(([^,\)]+)/);
    $obs{SIM_OFFSET_X} = $2
	if (/SIM_OFFSET=\(([^,\)]+),([^,]+)\)/);
    $obs{GRATING} = $1 if (/GRATING=([^,]+)/);

    return %obs;
}

	    
###############################################################
sub MM {
# Parse maneuver management (?) file
###############################################################
    my $mm_file = shift;
    my %mm;
    my $start_stop = 0;
    my $first = 1;

    open (MM, $mm_file) || confess "Couldn't open MM file $mm_file\n";
    while (<MM>) {
	chomp;
	$start_stop = !$start_stop if (/(INITIAL|INTERMEDIATE|FINAL) ATTITUDE/);
        $initial_obsid = $1 if (/INITIAL ID:\s+(\S+)\S\S/);
        $obsid = $1 if (/FINAL ID:\s+(\S+)\S\S/);
	$start_date = $1 if ($start_stop && /TIME\s*\(GMT\):\s+(\S+)/);
	$stop_date  = $1 if (! $start_stop && /TIME\s*\(GMT\):\s+(\S+)/);
	$ra         = $1 if (/RA\s*\(deg\):\s+(\S+)/);
	$dec        = $1 if (/DEC\s*\(deg\):\s+(\S+)/);
	$roll       = $1 if (/ROLL\s*\(deg\):\s+(\S+)/);
	$dur        = $1 if (/Duration\s*\(sec\):\s+(\S+)/);
	$angle      = $1 if (/Maneuver Angle\s*\(deg\):\s+(\S+)/);
	@quat       = ($1,$2,$3,$4) if (/Quaternion:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/);

	if (/Profile Parameters/) { # Effective end of maneuver statement
	    # If the FINAL ID was not found (in the case of an intermediate maneuver)
	    # then look ahead in the file to find it.  If that fails, use the initial obsid
	    unless ($obsid) {
		my $pos = tell MM;
		while (<MM>) {
		    if (/FINAL ID:\s+(\S+)\S\S/) {
			$obsid = $1;
			last;
		    }
		}
		$obsid = $initial_obsid unless ($obsid);
		seek MM, $pos, 0; # Go back to original spot
	    }
		    
	    while (exists $mm{$obsid}) { $obsid .= "!"; }

	    $mm{$obsid}->{start_date} = $start_date;
	    $mm{$obsid}->{stop_date}  = $stop_date;
	    $mm{$obsid}->{ra}         = $ra;
	    $mm{$obsid}->{dec}        = $dec;
	    $mm{$obsid}->{roll}       = $roll;
	    $mm{$obsid}->{dur}        = $dur;
	    $mm{$obsid}->{angle}      = $angle;
	    $mm{$obsid}->{tstart}     = date2time($start_date);
	    $mm{$obsid}->{tstop}      = date2time($stop_date);
	    ($mm{$obsid}->{obsid}     = $obsid) =~ s/^0+//;
	    $mm{$obsid}->{q1}         = $quat[0];
	    $mm{$obsid}->{q2}         = $quat[1];
	    $mm{$obsid}->{q3}         = $quat[2];
	    $mm{$obsid}->{q4}         = $quat[3];
	    undef $obsid;
	}
    }
    close MM;

    return %mm;
}

##***************************************************************************
sub mechcheck {
##***************************************************************************
    my $mc_file = shift;
    my @mc;
    my ($date, $time, $cmd, $dur, $text);
    my %evt;
    my $SIM_FA_RATE = 90.0;	# Steps per seconds  18steps/shaft

    open MC, $mc_file or confess "Couldn't open mech check file $mc_file\n";
    while (<MC>) {
	chomp;

	# Make continuity statements have similar format
	$_ = "$3 $1$2" if (/^(SIMTRANS|SIMFOCUS)( [-\d]+ at )(.+)/);

	next unless (/^(\d\d\d\d)(\d\d\d)\.(\d\d)(\d\d)(\d\d)(\d\d\d)(.+)/);
	$date = "$1:$2:$3:$4:$5.$6";
	$text = $7;
	%evt = ();
	$evt{time} = date2time($date);
	if ($text =~ /NO_MATCH_NOW_FOR_OBSID\s+(\d+)/) {
	    $evt{var} = "obsid";
	    $evt{dur} = 0;
	    $evt{val} = $1;
	} elsif ($text =~ /SIMTRANS ([-\d]+) at/) {
	    $evt{var} = "simtsc_continuity";
	    $evt{dur} = 0;
	    $evt{val} = $1;
	} elsif ($text =~ /SIMFOCUS ([-\d]+) at/) {
	    $evt{var} = "simfa_continuity";
	    $evt{dur} = 0;
	    $evt{val} = $1;
	} elsif ($text =~ /SIMTRANS from ([-\d]+) to ([-\d]+) Dur (\d+)/) {
	    $evt{var} = "simtsc";
	    $evt{dur} = $3;
	    $evt{val} = $2;
	    $evt{from} = $1;
	} elsif ($text =~ /SIMFOCUS from ([-\d]+) to ([-\d]+)/) {
	    $evt{var} = "simfa";
	    $evt{dur} = ceil(abs($2 - $1) / $SIM_FA_RATE);
	    $evt{val} = $2;
	    $evt{from} = $1;
	} elsif ($text =~ /NO_MATCH_NOW_FOR_GRATINGS (.+) to (.+)/) {
	    $evt{var} = "gratings";
	    $evt{dur} = 160;
	    $evt{val} = $2;
	    $evt{from}= $1;
	}
    
	push @mc, { %evt } if ($evt{var});
    }
    close MC;

    return @mc;
}

##***************************************************************************
sub parse_params {
##***************************************************************************
    my @fields = split '\s*,\s*', shift;
    my %param = ();
    my $pindex = 1;

    foreach (@fields) {
	if (/(.+)= ?(.+)/) {
	    $param{$1} = $2;
	} else {
	    $param{"anon_param$pindex"} = $_;
	    $pindex++;
	}
    }

    return %param;
}

