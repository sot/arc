#! /usr/bin/env /proj/sot/ska/bin/perlska

use warnings;
use strict;
use IO::All;
use Ska::RDB qw(read_rdb);
use Config::General;
use Data::Dumper;
use HTML::Table;
use Ska::Convert qw(time2date date2time);
use CGI;
use LWP::UserAgent;
use HTML::TableExtract;
use Quat;
use Carp;
use Hash::Merge;
use Time::Local;
use POSIX qw(floor);
use subs qw(dbg);

# Tasks:
# - Parse snapshot and get key values
# - Get iFOT data (radmon, comms, observations, load info)
# - Determine if SCS107 has likely run
# - Determine violations for current attitude (needs load info
#   to point into correct noodle location)
# - Generate timeline 

# ToDo:
# - Fix Ska::Convert to make time2date having configurable format
#   via { } at end.  Maintain stupid 2nd arg scalar for back-comp.

our %event_var = ();

our $Task     = 'arc';
our $TaskData = "$ENV{SKA_DATA}/$Task";

our $FloatRE = qr/[+-]?(?:\d+[.]?\d*|[.]\d+)(?:[dDeE][+-]?\d+)?/;
our $DateRE  = qr/\d\d\d\d:\d+:\d+:\d+:\d\d\.?\d*/;

# Set global current time at beginning of execution
our $CurrentTime = @ARGV ? date2time(shift @ARGV, 'unix') : time;	
our $SCS107date;
our $Debug = 0;
our @warn;	# Global set of processing warnings (warn but don't die)
our %opt;

# Read in config options and an optional test config options
Hash::Merge::set_behavior( 'RIGHT_PRECEDENT' );
foreach (qw(.cfg _test.cfg)) {
    my $cfg_file = "$TaskData/$Task$_";
    if (-e $cfg_file) {
	my %new_opt = ParseConfig(-ConfigFile => $cfg_file);
	%opt = %{ Hash::Merge::merge(\%opt, \%new_opt)};
    }
}

{
    ($SCS107date, my %scs_state) = check_for_scs107();
    my %snap = get_snapshot_data();
    $snap{$_}{value} = $scs_state{$_} foreach qw(scs107 scs128 scs129 scs130 scs_obt);

    # Get web data & pointers to downloaded image files from get_web_content.pl task
    my %web_content = ParseConfig(-ConfigFile => "$TaskData/$opt{file}{web_content}");

    my $obsid = $snap{obsid}{value};
    print STDERR Dumper(\%snap) unless (defined $obsid);
    my @event = get_iFOT_events(@{$opt{query_name}});

    make_maneuver_obsid_links(\@event);

    push @event, get_violation_events($obsid, \%snap, \@event);
    push @event, now_event();	# Add a special event for Now
    push @event, scs107_detected_event() if $SCS107date;

    @event = sort { $a->tstart <=> $b->tstart } @event;

    my $html  = make_web_page(\%snap, \@event, \%web_content);
    $html > io("$TaskData/$opt{file}{web_page}");
    install_web_files($html, \%web_content);

    print_iFOT_events(\@event) if $Debug;
    print join("\n", @warn), "\n" if $Debug;
}

####################################################################################
sub warning {
####################################################################################
    my $warning = shift;
    push @warn, $warning;
    print STDERR "$warning\n" if $Debug;
}

####################################################################################
sub now_event {
####################################################################################
    my $current_date = time2date($CurrentTime, 'unix');
    return Event->new('Type Description' => 'Now',
		      'TStart (GMT)'     => $current_date,
		      'TStop (GMT)'     => $current_date,
		      'summary' => '--------------- NOW ---------------',
		     );
}

####################################################################################
sub scs107_detected_event {
####################################################################################
    return Event->new('Type Description' => 'SCS-107 (Detected)',
		      'TStart (GMT)'     => $SCS107date,
		      'TStop (GMT)'     => $SCS107date,
		      'summary' => 'SCS107 detected during realtime comm',
		     );
}

####################################################################################
sub get_obsid_event {
####################################################################################
    my $obsid = shift;
    my $snap  = shift;
    my $event = shift;
    my $warn_msg = "Unable to include PCAD or thermal violation events";

    my @obsid_evt = grep { defined $_->obsid } @{$event};
    my @index = grep { $obsid_evt[$_]->obsid == $obsid } (0..$#obsid_evt);
    if (@index != 1) {
	my $num = (@index == 0) ? 'No' : 'Multiple';
	warning("$num events found matching obsid=$obsid: $warn_msg");
	return;
    }

    # Temporarily disable pcad checking
    # return $obsid_evt[$index[0]];

    # Check if pcadmode is NPM, and if so look at attitude and make sure it matches
    # expected for obsid.  If not, try the next maneuver after current obsid.

    if ($snap->{pcadmode}{value} eq 'NPNT') {
	my $snap_quat = Quat->new($snap->{ra}{value}, $snap->{dec}{value}, $snap->{roll}{value});
	for my $i ($index[0], $index[0]+1) {
	    unless (defined $obsid_evt[$i]->target_quat) {
		dbg Dumper $obsid_evt[$i];
		next;
	    }
	    my $target_quat = $obsid_evt[$i]->target_quat->quat;
	    my $dq = $target_quat->divide($snap_quat);
	    if (abs($dq->{ra0}) < 0.1 and abs($dq->{dec}) < 0.1 and abs($dq->{roll0}) < 1) {
		return $obsid_evt[$i];
	    }
	}
	warning("No obsid event matching snapshot attitude: $warn_msg");
    } else {
	# Not in NPM, so all bets are off
	warning("Not in NPM: $warn_msg");
    }

    # Failed to find obsid event corresponding to current obsid and attitude.
    # So return empty handed, which in turn causes get_violation_events to do nothing.
    return;			
}
    

####################################################################################
sub make_maneuver_obsid_links {
####################################################################################
    my $event = shift;
    my $obsid;
    my @link_types = qw(load_segment maneuver target_quat);
    my %link;
    local $_;

    for my $evt (@{$event}) {
	foreach (@link_types) {
	    $link{$_} = $evt if $evt->type eq $_;
	}

	if ($evt->type =~ /\A (observation | er) \Z/x) {
	    $obsid  = $evt->obsid;
	    foreach (@link_types) {
		$evt->$_($link{$_}) if defined $link{$_};
	    }
	    # Check for load segment tstart/tstop in range?
	    # if (defined $load_segment
	    #	  and $load_segment->tstart <= $evt->tstart
	    #	  and $load_segment->tstop  >= $evt->tstart);
	    dbg Dumper $evt if $evt->obsid == 5658;
	}
    }
}

####################################################################################
sub get_violation_events {
####################################################################################
    my $obsid = shift;
    my $snap = shift;
    my $event = shift;
    my $evt;
    my @violation;
    local $_;
    
    my $obsid_evt = get_obsid_event($obsid, $snap, $event) or return;
    my $time_maneuver = $obsid_evt->maneuver->tstop;
    my $date_maneuver = $obsid_evt->maneuver->date_stop;
    my $load_name = $obsid_evt->load_segment->load_name;
    my @constraints = get_pcad_constraints($load_name);

    my $constraint;
    for $constraint (@constraints) {
	my $time_constr = date2time($constraint->{date}, 'unix');
	my $delta_t = $time_constr - $time_maneuver;
	if (abs($delta_t) < 60) {
	    if ($Debug) {
		print "Found matching PCAD constraint record (delta = $delta_t):\n";
		print " pcad: ", $constraint->{date}, "\n";
		print " manv: $date_maneuver\n";
	    }

	    push @violation, Event->new('Type Description' => 'Violation',
					'TStart (GMT)'     => $constraint->{high_mom},
					'TStop (GMT)'     => $constraint->{high_mom},
					'violation' => 'High momentum'
				       );

	    push @violation, Event->new('Type Description' => 'Violation',
					'TStart (GMT)'     => $constraint->{attitude}{date},
					'TStop (GMT)'     => $constraint->{attitude}{date},
					'violation' => "Attitude violation: $constraint->{attitude}{type}"
				       );
	}
    }
    
    return @violation;
}

####################################################################################
sub get_pcad_constraints {
####################################################################################
    my $load_name = shift;
    my @constraint;
    local $_;

    # First get the PCAD constraint check file
    my ($mon, $day, $yr, $rev) = ($load_name =~ /(\w\w\w)(\d\d)(\d\d)(\w)/);
    my $year = $yr + 1900 + ($yr<97 ? 100 : 0);
    my $url = "$opt{url}{approved_loads}/$year/$mon/$load_name/output/$load_name.txt";
    my $constraints;
    
    $constraints = get_url($url,
			   user => $opt{authorization}{user},
			   passwd => $opt{authorization}{passwd},
			   timeout => $opt{timeout}
			  );

    # Parse the constraints
    #  Target Start Time:  2005:129:13:00:49.299
    #  Target Quaternion:  0.52572223 -0.74339168 -0.30769906 0.27623582 
    #  Target RA/Dec/Roll: 252.80 5.00 131.34 
    #  Attitude Violation: SPM 2005:135:06:20:49.000
    #  High Momentum:      2005:134:12:15:49.299
    $_ = $constraints;

    my @match;
    /Attitude Hold violation predictions\s*/g; 
    /\G%-+\s*/g;

    while (1) {
	my ($date, $quat, $att, $att_viol, $high_mom);
	
	if (/\G\s*Target Start Time:\s*($DateRE)\s*/g) { $date = $1 } else { last }
	if (/\GTarget Quaternion:\s*($FloatRE)\s+($FloatRE)\s+($FloatRE)\s+($FloatRE)\s*/g) {
	    $quat = [$1, $2, $3, $4]; } else { last }
	if (/\GTarget RA\/Dec\/Roll:\s*($FloatRE)\s+($FloatRE)\s+($FloatRE)\s*/g) {
	    $att = [$1, $2, $3] } else { last; }
	if (/\GAttitude Violation:\s*(\S+)\s+($DateRE).*\s*/g) {
	    $att_viol = { type => $1, date => $2 } } else { last }
	if (/\GHigh Momentum:\s*($DateRE).*/g) {
	    $high_mom = $1 } else { last }
	  
	# Could clean this up to make a more extensible structure (e.g. thermal)
	# Then need to adjust corresponding bit in get_violation_events
	push @constraint, {date   => $date,
			   quat   => $quat,
			   att    => $att,
			   attitude => $att_viol ,
			   high_mom => $high_mom
			  };
    }

    return @constraint;
}

####################################################################################
sub get_url {
####################################################################################
    my $url = shift;
    my %opt = (timeout => 60,
	       @_);

    my $user_agent = LWP::UserAgent->new;
    $user_agent->timeout($opt{timeout});
    my $req = HTTP::Request->new(GET => $url);
    $req->authorization_basic($opt{user}, $opt{passwd})
      if (defined $opt{user} and defined $opt{passwd});

    
    my $response = $user_agent->request($req);
    if ($response->is_success) {
	return $response->content;
    } else {
	croak $response->status_line;
    }
}

####################################################################################
sub get_current_load_name {
####################################################################################
    my $event = shift;
    local $_;
    my @rev_event = sort { $b->tstart <=> $a->tstart } @{$event};
    
    # really need to figure out load of current obsid if SCS107 has run
    for (@rev_event) {
	# Probably need to compare against SCS107 time?  errr.
	if ($_->type eq 'load_segment' and $_->tstart <= $CurrentTime) {
	    return uc $_->get('LOADSEG.LOAD_NAME');
	}
    }
    return 0;  # gotta do better than this
}

####################################################################################
sub make_web_page {
####################################################################################
    my $snap = shift;
    my $event = shift;
    my $web_data = shift;
    my $html = "";
    my $q = CGI->new;
    my @table;
    my $table;
    local $_;

#<img src="chandra_trw_small.gif" style="text-align:left; position:absolute; left:250px;top:70px" />
#<img src="goes_small.png" style="position:absolute; left:0px;top:0px" />
#n<img src="ace_small.png" style="align:right; position:absolute; left:550px; top:60px" />
#<span style="position:absolute; left:250px;top:15px;color:#cc0066;font-size:250%; font-weight:bold">Replan Central</span>
#<pre style="margin:100px"> </pre>

    $html .= $q->start_html(-title => $opt{web_page}{title_short},
			   -style => {-code => $opt{web_page}{style} }
			   );
    $html .= $q->img({src => "$opt{file}{goes_image}",
		      style => "position:absolute; left:0px;top:0px"});
    $html .= $q->img({src => "$opt{file}{chandra_image}",
		      style => "position:absolute; left:250px;top:70px"});
    $html .= $q->img({src => "$opt{file}{ace_image}",
		      style => "position:absolute; left:550px;top:60px"});
    $html .= $q->span({style=>"position:absolute;left:250px;top:15px;color:#cc0066;font-size:250%; font-weight:bold"}, $opt{web_page}{title});
    $html .= $q->pre({style=>"margin:220px"}, "");

    $html .= make_warning_table(@warn) . $q->p if (@warn);
    $html .= make_report_times_table($snap) . $q->p;
    $html .= make_snap_table($snap) . $q->p;
    $html .= make_event_table($event) . $q->p;

    $html .= make_ephin_goes_table($snap, $web_data) . $q->p;
    $html .= make_ace_table($snap, $web_data) . $q->p;

    my $image_title_style = "text-align:center;$opt{web_page}{table_caption_style}";
    $html .= $q->p({style => $image_title_style},
		   $q->a({href=>$opt{url}{mta_ace}}, "ACE particle Rates"),
		   $q->br, 
		   $q->img({style=>"margin-top:0.35em", src => $web_data->{ace}{image}{five_min}{file}}),
		  );

    $html .= $q->p({style => $image_title_style},
		   $q->a({href => $opt{url}{mta_goes}}, "GOES particle rates"),
		   $q->br,
		   $q->img({style=>"margin-top:0.35em", src => $web_data->{goes}{image}{five_min}{file}})
		  );

    $html .= $q->p({style => $image_title_style},
		   $q->a({href => $opt{url}{todays_space_weather}}, "Solar X-ray Activity"),
		   $q->br,
		   $q->img({style=>"margin-top:0.35em", src => $web_data->{space_weather}{image}{GOES_xray}{file}})
		  );

    $html .= $q->end_html;
    
    return $html;
}

####################################################################################
sub install_web_files {
####################################################################################
    my $html = shift;
    my $web_content = shift;
    local $_;

    # Ensure that web dir exists
    return unless (-d $opt{file}{web_dir});

    $html > io("$opt{file}{web_dir}/$opt{file}{web_page}");

    foreach (qw(chandra_image ace_image goes_image)) {
	io("$TaskData/$opt{file}{$_}") > io("$opt{file}{web_dir}/$opt{file}{$_}");
    }

    # Go through each web site where data/images were retrieved
    foreach my $web (values %{$web_content}) {
	next if defined $web->{warn}; # Skip if there was a warning
	foreach my $image (values %{$web->{image}}) {
	    next if defined $image->{warn};
	    next unless defined $image->{outfile};

	    # Copy new image file if infile exists and outfile either does not exist
	    # or is older than infile
	    my $in = io($image->{outfile});
	    my $out = io($opt{file}{web_dir} . "/" . $image->{file});
	    $in > $out if (defined $in->mtime
			   and ((not defined $out->mtime) or $in->mtime > $out->mtime));
	}
    }
}

####################################################################################
sub average {
####################################################################################
    my $arr = shift;
    return unless defined $arr and @{$arr};
    local $_;
    my $sum = 0;
    $sum += $_ foreach @{$arr};
    return $sum / @{$arr};
}

####################################################################################
sub make_warning_table {
####################################################################################
    my @warn = @_;
    my @table = map { [$_] } @warn;
    my $table = new HTML::Table(-align => 'center',
				-border => 2,
				-spacing => 0,
				-padding => 2,
				-style => 'color:red',
				-rules => 'none',
				-data  => \@table,
			       );
    
    $table->setColStyle(1,"font-size:120%");
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}> " .
		       " Processing Warnings</span>", 'TOP');
    return $table->getTable;
}

####################################################################################
sub make_ace_table {
####################################################################################
    my $snap = shift;
    my $web_data = shift;
    local $_;

    my @table;
    my %val;
    my %tab_def = %{$opt{ace_table}};
    my $n_row = @{$tab_def{row}}+1; # Including row and col headers
    my $n_col = @{$tab_def{col}}+1;

    my $start = qr/YR \s+ MO \s+ DA \s+ HHMM \s+ 38-53 .+ \s*/x;
    my ($ace_date, $ace_p3) = parse_mta_rad_data($start,
						 $web_data->{ace}{content}{flux}{content},
						7);

    return '<h2 style="color:red;text-align:center">NO RECENT ACE DATA</h2>' unless (@{$ace_p3});

    my ($fluence_date, $orbital_fluence) = parse_mta_rad_data(qr/ACIS Fluence data...Start DOY,SOD/,
							      $web_data->{acis_ace}{content}{ace_fluence}{content},
							      9 );
    $orbital_fluence = $orbital_fluence->[0];
    my $orbital_fluence_limit = 2e9;
    my $orbital_flux_limit = $orbital_fluence_limit / 170000;
    my $two_hr_limit = '50000';
    my $last_p3 = $ace_p3->[-1];
    my $avg_p3 = average($ace_p3);

    my $hours_to_limit = '&gt 30';
    if ($orbital_fluence > $orbital_fluence_limit) {
	$hours_to_limit = 0;
    } elsif ($last_p3 > 10) {
	my $hours = ($orbital_fluence_limit - $orbital_fluence) / $last_p3 / 3600;
	$hours_to_limit = format_number($hours, 2) if $hours < 30;
    } 

    $val{'Current flux'}{Value} = format_number($last_p3 , 3);
    $val{'Current flux'}{'2hr limit'} = format_number($two_hr_limit, 3);
    $val{'Current flux'}{'Orbital limit'} = format_number($orbital_flux_limit, 2);
    $val{'Current flux'}{'Hours to<br>Orbital limit'} = $hours_to_limit;

    $hours_to_limit = '&gt 30';
    if ($orbital_fluence > $orbital_fluence_limit) {
	$hours_to_limit = 0;
    } elsif ($avg_p3 > 10) {
	my $hours = ($orbital_fluence_limit - $orbital_fluence) / $avg_p3 / 3600;
	$hours_to_limit = format_number($hours,2) if $hours < 30;
    } 
    $val{'2hr avg flux'}{Value} = format_number($avg_p3 , 3);
    $val{'2hr avg flux'}{'2hr limit'} = format_number($two_hr_limit, 3);
    $val{'2hr avg flux'}{'Orbital limit'} = format_number($orbital_flux_limit, 2);
    $val{'2hr avg flux'}{'Hours to<br>Orbital limit'} = $hours_to_limit;

    $val{'Orbital fluence'}{Value} = format_number($orbital_fluence, 2);
    $val{'Orbital fluence'}{'2hr limit'} = '---';
    $val{'Orbital fluence'}{'Orbital limit'} = format_number($orbital_fluence_limit, 2);
    $val{'Orbital fluence'}{'Hours to<br>Orbital limit'} = '---';

    my $i = 0;
    for my $row (@{$tab_def{row}}) {
	my $j = 0;
	$table[$i+1][0] = $tab_def{row}[$i];
	for my $col (@{$tab_def{col}}) {
	    $table[0][$j+1] = $tab_def{col}[$j];
	    $table[$i+1][$j+1] = defined $val{$row}{$col} ? $val{$row}{$col} : '';
	    $j++;
	}
	$i++;
    }

    my $footnotes = "ACE data from $ace_date";
    $footnotes .= "<br>Orbital fluence: integrated attenuated ACE flux";
    $table[$n_row][0] = $footnotes;

    my $table = new HTML::Table(-align => 'center',
				-rules => 'all',
				-border => 2,
				-spacing => 0,
				-padding => 2,
				-data  => \@table,
			       );
    $table->setCellHead(1,$_) foreach (1..$n_col);
    $table->setCellHead($_,1) foreach (1..$n_row);
    for $i (2..$n_row) {
	for my $j (2..$n_col) {
	    $table->setCellAlign($i,$j,'RIGHT');
	}
    }
    $table->setCellColSpan($n_row+1, 1, $n_col);
    $table->setCellStyle($n_row+1, 1, $tab_def{footnote_style});
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}> " .
		       " ACE rates</span>", 'TOP');

    return $table->getTable;
}

####################################################################################
sub make_ephin_goes_table {
####################################################################################
    my $snap = shift;
    my $web_data = shift;
    local $_;

    my @table;
    my %val;
    my %tab_def = %{$opt{ephin_goes_table}};

    my $start = qr/P1 \s+ P2  \s+ P5 \s+ P8  \s+ P10 \s+ P11/x;

    my ($goes_date, $p2, $p5) = parse_mta_rad_data($start,
						   $web_data->{goes}{content}{flux}{content},
						   5, 6,
						  );
    
    my $warning = (@{$p2} == 0 || @{$p5} == 0) ?
      '<h2 style="color:red;text-align:center">NO RECENT GOES DATA</h2>' : '';

    my $ephin_date = $snap->{obt}{value} . ' (' .
		  Event::calc_delta_date($snap->{obt}{value}) . ')';

    $val{GOES}{P4GM}  = @{$p2} ? format_number(average($p2) * 3.3, 2) : '---'; # See http://asc.harvard.edu/mta/G10.html
    $val{GOES}{P41GM} = @{$p5} ? format_number(average($p5) * 12,2) : '---'; # ditto
    $val{EPHIN}{E1300} = sprintf("%.1f", $snap->{E1300}{value});
    $val{EPHIN}{P4GM}  = sprintf("%.1f",$snap->{P4GM}{value});
    $val{EPHIN}{P41GM} = sprintf("%.1f",$snap->{P41GM}{value});
    $val{Limit}{E1300} = 10.0;
    $val{Limit}{P4GM} = 300.0;
    $val{Limit}{P41GM} = 8.47;
	
    my $n_row = @{$tab_def{row}}+1; # Including row and col headers
    my $n_col = @{$tab_def{col}}+1;

    my $i = 0;
    for my $row (@{$tab_def{row}}) {
	my $j = 0;
	$table[$i+1][0] = $tab_def{row}[$i];
	for my $col (@{$tab_def{col}}) {
	    $table[0][$j+1] = $tab_def{col}[$j];
	    $table[$i+1][$j+1] = defined $val{$col}{$row} ? $val{$col}{$row} : '';
	    $j++;
	}
	$i++;
    }

    my $footnotes = "EPHIN: from snapshot at $ephin_date<br />";
    $footnotes .= "GOES: scaled two hour average of GOES-11 <br /><span style=\"padding:1.6em\"></span>from $goes_date";
    $table[$n_row][0] = $footnotes;

    my $table = new HTML::Table(-align => 'center',
				-rules => 'all',
				-border => 2,
				-spacing => 0,
				-padding => 2,
				-data  => \@table,
			       );
    $table->setCellHead(1,$_) foreach (1..$n_col);
    $table->setCellHead($_,1) foreach (1..$n_row);
    for $i (2..$n_row) {
	for my $j (2..$n_col) {
	    $table->setCellAlign($i,$j,'RIGHT');
	}
    }
    $table->setCellColSpan($n_row+1, 1, $n_col);
    $table->setCellStyle($n_row+1, 1, $tab_def{footnote_style});
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}> " .
		       " EPHIN and GOES rates</span>", 'TOP');
    return $warning . $table->getTable;
}

####################################################################################
sub parse_mta_rad_data {
####################################################################################
    my $start = shift;
    local $_ = shift;
    my @col = @_;
    my $date;
    my $valid_val;
    my @dat;


    /$start\s*/gx;
    
    while (/\G \s* (\d\d\d\d .+) \s*/gx) {
	my @val = split ' ', $1;
	my $all_ok = 1;
	for my $i (0..$#col) {
	    if ($val[$col[$i]] > 0) {
		push @{$dat[$i]}, $val[$col[$i]] ;
	    } else {
		$all_ok = 0;
	    }
	}
	# Keep track of the last set of good data to extract time/date
	$valid_val = [ @val ] if $all_ok;
    }

    # If there was some good data, then compute date and rel date.
    if ($valid_val) {
	my ($year, $mon, $mday, $hhmm) = @{$valid_val};
	my $min = $hhmm % 100;
	my $hour = POSIX::floor($hhmm / 100);
	my $time = timegm(0, $min, $hour, $mday, $mon-1, $year);
	$date = Event::format_date(time2date($time, 'unix')) 
	  . ' (' . Event::calc_delta_date($time) . ')';
    }
    return ($date, @dat);
}

####################################################################################
sub make_event_table {
####################################################################################
    my $event = shift;
    my @table = ();

    # Collect the event data into a table array.  Keep track of the color of each row
    my @col = @{$opt{event_table}{col}};
    my @row_bg_color = ();
    my @row_font_color = ();

    foreach my $evt (@{$event}) {
	next unless exists $opt{event_table}{$evt->type};
	next unless (($CurrentTime - $evt->tstart < $opt{event_table}{display_range}{hours_pre}*3600
		      and $evt->tstop - $CurrentTime < $opt{event_table}{display_range}{hours_post}*3600)
		     or $evt->type eq 'violation');
	push @table, [ map { $evt->$_ } @col ];
	push @row_bg_color, $opt{event_table}{$evt->type};
	push @row_font_color, get_event_font_color($evt);
    }

    my $table = new HTML::Table(-align => 'center',
				-rules => 'all',
				-border => 2,
				-spacing => 0,
				-padding => 2,
				-head=> ['Time (UT)', 'Event', 'Delta time', 'Time (Eastern)'],
				-data  => \@table,
			       );

    # Set the formatting of columns
    for (0..$#col) {
	my $ec = $opt{event_table}{$col[$_]};
	$table->setColAlign($_+1, $ec->{align}) if $ec->{align};
	my $pre = $ec->{format_pre} || '';
	my $post = $ec->{format_post} || '';
	$table->setColFormat($_+1, $pre, $post);
    }

    # Set the color of each row
    for (0..$#row_bg_color) {
	if (defined $row_bg_color[$_]) {
	    my $bg_color = $opt{color}{$row_bg_color[$_]};
	    $table->setRowBGColor($_+2, "#$bg_color") if defined $bg_color;
	}
	if (defined $row_font_color[$_]) {
	    my $font_color = $opt{color}{$row_font_color[$_]};
	    $table->setRowStyle($_+2, "color:#$font_color") if defined $font_color;
	}
    }

    $table->setRowAlign(1, 'CENTER');
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}>Chandra Events</span>", 'TOP');
    return $table->getTable;
}

####################################################################################
sub make_snap_table {
####################################################################################
    my $snap = shift;
    my @table;
    for my $row (split "\n", $opt{snap_format}) {
	my @cols = split(/\s*\|\s*/, $row);
	push @table, [ map { defined $snap->{$_} ? "$snap->{$_}{full_name} = $snap->{$_}{value}" : '' } @cols ];
    }

    my $table = new HTML::Table(-align => 'center',
			     -rules => 'all',
			     -border => 2,
			     -spacing => 0,
			     -padding => 2,
			     -data  => \@table,
			    );
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}>Key " .
		       "<a href=\"$opt{url}{mta_snapshot}\">Snapshot</a>" . 
		       " Values</span>", 'TOP');
    return $table->getTable;
}

####################################################################################
sub make_report_times_table {
####################################################################################
    my $snap = shift;
    my @table = (['Current time (UTC)',
		  Event::format_date(time2date($CurrentTime, 'unix_time')),
		  Event::calc_delta_date($CurrentTime),
		  Event::calc_local_date($CurrentTime)],
		 ['Snapshot time (OBT)',
		  $snap->{obt}{value},
		  Event::calc_delta_date($snap->{obt}{value}),
		  Event::calc_local_date($snap->{obt}{value})],
		 ['SCS status flags time (OBT)',
		  $snap->{scs_obt}{value},
		  Event::calc_delta_date($snap->{scs_obt}{value}),
		  Event::calc_local_date($snap->{scs_obt}{value})]
		);
    my $table = new HTML::Table(-align => 'center',
				-rules => 'all',
				-border => 2,
				-spacing => 0,
				-padding => 2,
				-head => ['', 'Time (UT)', 'Delta time', 'Time (Eastern)'],
				-data  => \@table,
			       );
    $table->setColAlign(3, 'RIGHT');
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}>Report Times</span>", 'TOP');

    return $table->getTable;
}

####################################################################################
sub get_event_font_color {
####################################################################################
    my $evt = shift;
    if ($SCS107date
	and ($evt->tstart > date2time($SCS107date,'unix'))
	and exists $opt{event_table}{scs107_disabled}{$evt->type}) {
      return 'event_disabled';
  } else {
      return undef;
  }

}

####################################################################################
sub get_iFOT_events {
####################################################################################
    my @table_id = @_;
    my @event;
    local $_;

    # Find the most recent iFOT event files which are older than the cutoff time.
    # This is to see the events just prior to an SCS107 run (e.g. what observations
    # were planned, when were the radmon en/disable etc.  If there was not an SCS107
    # run, then just use the current time plus a little pad.


    # Grab proper event data for each iFOT table specified in config file
    foreach my $table_id (@table_id) {
	my $cutoff_time = (defined $opt{stop_at_scs107}{$table_id} and defined $SCS107date) ? 
	  date2time($SCS107date, 'unix') :  $CurrentTime+10 ;
	my @files = reverse sort glob("$TaskData/$opt{file}{iFOT_events}/$table_id/*.rdb");
      FILE: foreach (@files) {
	    next unless m!/ ($DateRE) \.rdb \Z!x;
	    if (date2time($1, 'unix') < $cutoff_time) {
		print "Using event file $_\n" if $Debug;
		my @event_data = read_rdb($_);
		foreach (@event_data) {
		    push @event, Event->new( %{$_} );
		}
		last FILE;
	    }
	}
    }

    my @sort_event = sort { $a->tstart <=> $b->tstart } @event;
    
    return @sort_event;
}

####################################################################################
sub print_iFOT_events {
####################################################################################
    local $_;
    my $event = shift;

    foreach my $evt (@{$event}) {
	print join(" : ", $evt->date_start, $evt->delta_date, $evt->local_date, $evt->summary), "\n";
    }
}

####################################################################################
sub check_for_scs107 {
####################################################################################
    my $event = shift;
    my %scs_state;		
    local $_;

    my $snap_archive;
    foreach (glob "$opt{file}{snap_archive}.???????") {
	next unless /\d{7}\Z/;	# Make sure it ends with something like 2005128
	print "Snap archive file: $_\n" if $Debug;
	$snap_archive .= io($_)->slurp;
    }
    $snap_archive =~ s/<.*?>//g;	# Do the stupidest possible HTML tag removal.
				# since it's fast and works for snarc files
    # See HTML::FormatText for the "right" way to do it,  except that the damn 
    # thing doesn't work for <pre> with HTML formatting tags!
 
    # Split on the UTC key, but then put it back into each snapshot
    my @snap_archive = map { "UTC $_" } split /^UTC/m, $snap_archive;

    my @snap = map { { get_snapshot_data($_) } } @snap_archive;
    @snap = reverse grep { defined $_->{utc}{value} } @snap;

    # Most recent state of SCS slots 107, 128, 129, 130.  But back up as far
    # as possible in time to get the earliest detection of SCS107 run.

SNAP: for my $snap (@snap) {
	# Don't use a snapshot newer than CurrentTime (mostly relevant for testing)
	next SNAP unless date2time($snap->{obt}{value}, 'unix') < $CurrentTime;

	my $have_scs_states = defined $scs_state{scs107};
	if ($snap->{format}{value} =~ /_eps/i) {
	    my %curr_scs_state = map { $_ => $snap->{$_}{value} } qw(scs107 scs128 scs129 scs130 obt utc);
	    print Dumper \%curr_scs_state if $Debug;
	    if ($have_scs_states) {
		# Check that the SCS state values are the same (guarding against invalid telem in snap)
		foreach (qw(scs107 scs128 scs129 scs130)) {
		    last SNAP if ($scs_state{$_} ne $curr_scs_state{$_});
		} 
	    }
	    %scs_state = %curr_scs_state;
	} elsif (defined $scs_state{scs107}) {
	    # Went back beyond contiguous segment of EPS subformat data, so bail out
	    last SNAP;
	}
    }

    print Dumper \%scs_state if $Debug;

# The algorithms below require that this code be run frequently (at least every 5 minutes)
# to ensure "seeing" the initial detection of SCS107 in the event of switching in and out
# of EPS subformat

    my $scs107_history_file = "$TaskData/$opt{file}{scs107_history}";
    my $load_running = (grep { $scs_state{"scs$_"} eq 'ACT' } qw(128 129 130)) ? 1 : 0;

    my $scs107_not_inac = ($scs_state{scs107} ne 'INAC') ? 1 : 0;
	
    # Go in to SCS107 history file and see if scs107 has already been detected
    my $scs107_detected = 0;
    my $scs107_detected_date;
    if (my $scs107_history = io($scs107_history_file)->[-1]) {
	dbg "scs107_history last line = $scs107_history\n";
	my ($date, $event) = split /\s*::\s*/, $scs107_history;
	dbg "event = $event\n";
	if ($event =~ /detected/i) {
	    $scs107_detected_date = $date;
	    $scs107_detected = 1;
	}
    }
    
# LdRun 107_dis 107_file  action
#   0     0      0        warn no loads running, no indication of SCS107
#   0     0      1        return time in file (could be SCS107 more than 3 days ago)
#   0     1      0        put scs107_detect time in file, return that time
#   0     1      1        return time in file
#   1     0      0        All is normal. return ().  
#   1     0      1        Return to normal after scs107 run.  Unlink file, return ().
#   1     1      0        Invalid combination.  Push warning, then as for (0,1,0)
#   1     1      1        Invalid combination.  Push warning, return time in file.

    my @a = ($load_running, $scs107_not_inac, $scs107_detected);
    print "scs107/load status: @a\n" if $Debug;

    if (array_eq(\@a, [0,0,0])) {
	warning("No load SCSs active and no indication of SCS107 run");
    } elsif (array_eq(\@a, [0,0,1])) {
	# No action req'd
    } elsif (array_eq(\@a, [0,1,0])) {
	$scs107_detected_date = $scs_state{obt};
	"$scs107_detected_date :: SCS107 detected\n" >> io($scs107_history_file);
    } elsif (array_eq(\@a, [0,1,1])) {
	# No action req'd
    } elsif (array_eq(\@a, [1,0,0])) {
	# No action req'd
    } elsif (array_eq(\@a, [1,0,1])) {
	"$scs_state{obt} :: Loads running\n" >> io($scs107_history_file);
	undef $scs107_detected_date;
    } elsif (array_eq(\@a, [1,1,0])) {
	warning("Loads apparently running and SCS107 not INAC at $scs_state{obt}");
	$scs107_detected_date = $scs_state{obt};
	"$scs107_detected_date :: SCS107 detected\n" >> io($scs107_history_file);
    } elsif (array_eq(\@a, [1,1,1])) {
	warning("Loads apparently running and SCS107 not INAC at $scs_state{obt}");
	# (scs107_detected_date already set)
    } 

    # Clean up %scs_state a bit so it can be easily merged with %snap to force
    # "good" values of the SCS status flags, without clobbering the existing OBT,UTC
    for (qw(obt utc)) {
	$scs_state{"scs_$_"} = $scs_state{$_};
	delete $scs_state{$_};
    }

    get_scs107_runtime($event, $scs107_history_file, \%scs_state) if ($scs107_detected_date);

    print "SCS107 detected at $scs107_detected_date\n" if $Debug and $scs107_detected_date;
    return $scs107_detected_date, %scs_state;
}

####################################################################################
sub get_scs107_runtime {
####################################################################################
    my $event = shift;
    my $scs107_history_file = shift;
    my $scs_state = shift;

    # Find when loads were last active to set a limit to the lookback time for an
    # SCS107 event

}

####################################################################################
sub array_eq {
####################################################################################
    my $a1 = shift;
    my $a2 = shift;

    for my $i (0..$#{$a1}) {
	return 0 if $a1->[$i] != $a2->[$i];
    }
    return 1;
}

####################################################################################
sub get_snapshot_data {
####################################################################################
    local $_;
    my $snap = shift || io($opt{file}{snap})->slurp;
    my %snap;

    $snap =~ s/\s+/ /g;
    while (my ($name, $delim) = each %{$opt{snap}}) {
	my ($full_name, $prec, $post) = split /\s* : \s*/x, $delim;
	my ($value) = ($snap =~ /${prec}\s*(\S+)\s*${post}/);
	$snap{$name} = { full_name => $full_name,
			 name      => $name,
			 value     => $value,
		       };
    }
    return %snap;
}


####################################################################################
sub format_number {
####################################################################################
    my $num = shift;
    my $nsig = shift;
    my $type = shift || 'auto';
    local $_;

    my $nsig1 = $nsig-1;
    $_ = sprintf("%.${nsig1}e", $num);
    my ($mant, $exp) = /([-.\d]+)e([-+]\d+)/;
    if ($type eq 'auto') {
	$type = ($num != 0 and (abs($num) >= 1e6 or abs($num) < 1e-3)) ? 'scientific' : 'normal';
    }

    if ($type eq 'scientific') {
	$exp = sprintf("%d", $exp);
	return "${mant}x10<sup>$exp</sup>";
    } else {
	return $mant * 10**$exp;
    }
}

##***************************************************************************
# our very own debugging routine
# ('guess everybody has its own style ;-)
sub dbg  {
##***************************************************************************
  if ($Debug) {
    my $args = join('',@_) || "";
    my $caller = (caller(1))[0];
    my $line = (caller(0))[2];
    $caller ||= $0;
    if (length $caller > 22) {
      $caller = substr($caller,0,10)."..".substr($caller,-10,10);
    }
    my $align = ' 'x39;
    $args =~ s/\n/\n$align/g;
    print STDERR sprintf ("%02d:%02d:%02d [%22.22s %4.4s]  %s\n",
			  (localtime)[2,1,0],$caller,$line,$args);
  }
}

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

##***************************************************************************
sub new {
##***************************************************************************
    my $class = shift;
    my $evt = { @_ };
    bless ($evt, $class);

    my %event_type = ('DSN Comm Time'             => 'comm_pass'   ,
		      'Observation'               => 'observation' ,
		      'Target Quaternion'         => 'target_quat' ,
		      'Maneuver'                  => 'maneuver'    ,
		      'Acquisition Sequence'      => 'acq_seq'     ,
		      'Radmon Processing Enable'  => 'radmon_enab' ,
		      'Radmon Processing Disable' => 'radmon_dis'  ,
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
	    $evt->{summary} = sprintf("Maneuver to %.5f %.5f %.3f",
				      $targ->{ra},
				      $targ->{dec},
				      $targ->{roll});
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

    $evt->{summary} = sprintf("Uplink %s:%s (%s to %s)",
			      $evt->{'LOAD_UPLINK.LOAD_NAME'},
			      $evt->{'LOAD_UPLINK.NAME'},
			      $delta_date_start,
			      $delta_date_stop
			     );
}
			      
			      
sub init_load_segment {
    my $evt = shift;
    local $_;

    my $delta_date_start = calc_delta_date(date2time($evt->{tstart},'unix'), $CurrentTime);
    my $delta_date_stop  = calc_delta_date(date2time($evt->{tstop},'unix'), $CurrentTime);
    $delta_date_start =~ s/\A\s+|\s+\Z//g;
    $delta_date_stop =~ s/\A\s+|\s+\Z//g;

    $evt->{summary} = sprintf("Load %s:%s (%s to %s)",
			      $evt->{'LOADSEG.LOAD_NAME'},
			      $evt->{'LOADSEG.NAME'},
			      $delta_date_start,
			      $delta_date_stop
			     );
}
			      
			      

sub init_comm_pass {
    my $evt = shift;
    my $sec_per_day = 86400;
    local $_;
    # Change date_start, date_stop, (and tstart and tstop) to correspond to
    # BOT and EOT instead of station callup.  Some shenanigans are required
    # because the iFOT values DSN_COMM.bot/eot are just 24 hour times and
    # not a full date, so we need to worry about day rollovers.

    my %track;
    $track{start} = $evt->{'DSN_COMM.bot'};
    $track{stop} = $evt->{'DSN_COMM.eot'};

    for (qw(start stop)) {
	my ($year, $doy, $hour, $min, $sec) = split ':', $evt->{"date_$_"};
	$hour = substr $track{$_}, 0, 2;
	$min  = substr $track{$_}, 2, 2;
	my $track_time = date2time(join(":", ($year, $doy, $hour, $min, $sec)), 'unix_time');

	# Correct for any possible day rollover in the bot/eot time specification
	if (abs(my $time_delta = $track_time - $evt->{"t$_"}) > $sec_per_day/2) {
	    $track_time += $sec_per_day * ($time_delta > 0 ? -1 : 1);
	}

	$evt->{"date_$_"} = format_date(time2date($track_time, 'unix_time'));
	$evt->{"t$_"} = $track_time;
    }

    $evt->{summary} = sprintf("Comm pass on %s (duration %s)",
			      $evt->{'DSN_COMM.station'},
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
    $t2 = date2time($t2, 'unix') if ($t1 =~ /$DateRE/);

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
