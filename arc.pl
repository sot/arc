#! /usr/bin/env perl

use warnings;
use strict;
use IO::All;
use Ska::RDB qw(read_rdb);
use Ska::Run;
use Ska::Convert qw(time2date date2time);
use Ska::Web;
use Config::General qw(ParseConfig);
use Data::Dumper;
use HTML::Table;
use CGI;
use LWP::UserAgent;
use HTML::TableExtract;
use Quat;
use Carp;
use Hash::Merge;
use Time::Local;
use POSIX qw(floor);
use subs qw(dbg);
use Chandra::Time;
use Safe;
use Getopt::Long;
use Net::Netrc;

# ToDo:
# - Fix Ska::Convert to make time2date having configurable format
#   via { } at end.  Maintain stupid 2nd arg scalar for back-comp.
# - Improve get_obsid_event so that it does violation checks during manv'r
# - Make sure logs and all other files w/ passwd are secure

our $Task     = 'arc3';
our $TaskData = "$ENV{SKA_DATA}/$Task";
our $TaskShare = "$ENV{SKA_SHARE}/$Task";
our $VERSION = '4.10.2';

require "$ENV{SKA_SHARE}/$Task/Event.pm";
require "$ENV{SKA_SHARE}/$Task/Snap.pm";
require "$ENV{SKA_SHARE}/$Task/parse_cm_file.pl";

our $FloatRE = qr/[+-]?(?:\d+[.]?\d*|[.]\d+)(?:[dDeE][+-]?\d+)?/;
our $DateRE  = qr/\d\d\d\d:\d+:\d+:\d+:\d\d\.?\d*/;

our %opt = get_config_options();

# Set global current time at beginning of execution
our $CurrentTime = @ARGV ? date2time(shift @ARGV, 'unix') : time;
our $CURRENT_TIME = Chandra::Time->new($CurrentTime, {format => 'unix'});
our $conv_time = Chandra::Time->new({format => 'unix'}); # Generic time converter box

our $SCS107date;
our %load_info;
our $Debug = 0;
our @warn;	# Global set of processing warnings (warn but don't die)

Event::set_CurrentTime($CurrentTime);
Snap::set_CurrentTime($CurrentTime);
Snap::set_snap_definition($opt{snap_definition});

umask 002;

# Get authorization for access to OCCweb
my $netrc = Net::Netrc->lookup('occweb');
my $occweb_user = $netrc->login;
my $occweb_passwd = $netrc->password;
{
    # Substitute any ENV vars in $opt{file}.  Do this in a Safe way.
    interpolate_config_file_options();

    # Get web data & pointers to downloaded image files from get_web_content.pl task
    my %web_content = ParseConfig(-ConfigFile => "$TaskData/$opt{file}{web_content}");

    my ($snap_warning_ref, %snap) = Snap::get_snap( $opt{file}{snap_archive},
						    [ $opt{file}{snap},
						      $web_content{snapshot}{content}{snapshot}{outfile},
						    ],
						  );
    # Info from snapshot is *req'd* for subsequent processing.  Snapshot unavailability
    # is almost always transient
    die(@{$snap_warning_ref}) if @{$snap_warning_ref};

    $SCS107date = check_for_scs107(\%snap);

    my $obsid = $snap{obsid}{value};
    my @event = get_iFOT_events(@{$opt{query_name}});

    make_maneuver_obsid_links(\@event);

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
    while (my $warning = shift) {
	push @warn, $warning;
	print STDERR "$warning\n" if $Debug;
    }
}

####################################################################################
sub interpolate_config_file_options {
# Substitute any ENV vars in $opt{file}.  Do this in a Safe way.
####################################################################################
    my $safe = new Safe;
    $safe->share('%ENV');
    $safe->permit_only(qw(:base_core :base_mem :base_orig));
    foreach (values %{$opt{file}}) {
	if (defined $_) {
	    $_ = $safe->reval(qq{"$_"});
	    die "ERROR - problem in safe eval of file option: $@\n" if $@;
	}
    }
}

####################################################################################
sub get_config_options {
####################################################################################
# Read in config options and an optional test config options
    my %opt = ('config' => "arc3");
    GetOptions(\%opt,
	       'config=s');

    Hash::Merge::set_behavior( 'RIGHT_PRECEDENT' );
    foreach (split(':', $opt{config})) {
	my $cfg_file = "$TaskShare/$_.cfg";
	if (-r $cfg_file) {
	    my %new_opt = ParseConfig(-ConfigFile => $cfg_file);
	    %opt = %{ Hash::Merge::merge(\%opt, \%new_opt)};
	}
    }
    return %opt;
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
sub make_maneuver_obsid_links {
####################################################################################
    my $event = shift;
    my $obsid;
    my @link_types = qw(load_segment maneuver target_quat);
    my %link;
    local $_;
    my $evt2;

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
	}
	if ($evt->type eq 'maneuver'
	    and defined ($evt2 = $link{target_quat})
	    and abs($evt->tstart - $evt2->tstart) < 30) {
	    $evt->target_quat($evt2);
	    $evt2->maneuver($evt);
	}
	if ($evt->type eq 'target_quat'
	    and defined ($evt2 = $link{maneuver})
	    and abs($evt->tstart - $evt2->tstart) < 30) {
	    $evt->maneuver($evt2);
	    $evt2->target_quat($evt);
	}

    }
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
	return ($response->content, undef);
    } else {
	return (undef, $response->status_line . "\n$url\n");
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

    $html .= $q->start_html(-title => $opt{web_page}{title_short},
			    -style => [{-code => $opt{web_page}{style} },
				       {-src => "timeline.css",}
				       ],
			    -noScript => $opt{web_refresh}{NoScript},
			    -script => [{ -src => 'timeline_states.js'},
					{ -src => 'timeline.js'},
					{ -language => 'JavaScript',
					  -code     => $opt{web_refresh}{JavaScript},
					},
					{ -language => 'JavaScript1.1',
					  -code     => $opt{web_refresh}{JavaScript11},
					},
					{ -language => 'JavaScript1.2',
					  -code     => $opt{web_refresh}{JavaScript12},
					},
				       ],
			    -onLoad => 'doLoad(); initTimeLineHandlers()',
			   );
    $html .= $q->p({style => "text-align:center"},
		   $q->img({src => "$opt{file}{title_image}"}));

    $html .= $q->p({style => 'font-size:130%; font-weight:bold; text-align:center'},
		       "Page content updated: ",
		       Event::format_date(time2date($CurrentTime, 'unix_time')),
		       " (", Event::calc_local_date($CurrentTime), ")"
		      );

    $html .= make_warning_table(@warn) . $q->p if (@warn);

    my $snap_table = make_snap_table($snap) . $q->p;

    $html .= HTML::Table->new(-align => 'center',
			      -padding => 2,
			      -data   => [[$q->img({src=>$web_data->{orbit_image}{content}{orbit}{file}}),
					  $snap_table]],
			     )->getTable;

    $html .= $opt{timeline_html};

    my $avail_comms_html < io("$TaskData/comms_avail.html");
    $html .= $avail_comms_html;

    $html .= $q->p . make_event_table($event) . $q->p;

    $html .= HTML::Table->new(-align => 'center',
			      -padding => 2,
			      -data   => [[make_ephin_goes_table($snap, $web_data),
					   make_ace_table($snap, $web_data)]]
			      )->getTable;

    my $image_title_style = "text-align:center;$opt{web_page}{table_caption_style}";
    $html .= $q->p({style => $image_title_style},
		   "ACE particle rates (",
		   $q->a({href=>$opt{url}{mta_ace}, target => "_blank"}, "MTA"),
		   $q->a({href=>$opt{url}{swpc_ace_rtsw}, target => "_blank"}, "SWPC"),
		   ")",
		   $q->br,
		   $q->img({class=>"boxed", src => $web_data->{ace}{image}{five_min}{file}}),
		  );

    $html .= $q->p({style => $image_title_style},
		   $q->a({href => $opt{url}{mta_goes}, target => "_blank"}, "GOES particle rates"),
		   $q->br,
		   $q->img({class=>"boxed", width => 700,
			    src => $web_data->{goes}{image}{five_min}{file}})
		  );

    $html .= $q->p({style => $image_title_style},
    "GOES proxy for HRC shield rates",
    $q->br,
    $q->img({class=>"boxed", src => "hrc_shield.png"})
    );

    $html .= # $q->div({style => 'width:700'},
		   make_solar_forecast_table($web_data);
#		   );

    $html .= $q->p({style => $image_title_style},
		   $q->a({href => $opt{url}{goes_xray_flux}, target => "_blank"}, "Solar X-ray Activity"),
		   $q->br,
		   $q->img({class=>"boxed", src => 'goes_x.png'})
		  );

    $html .= $q->p({style => $image_title_style},
                   "Solar Wind Data (",
		   $q->a({href => $opt{url}{soho_solar_wind}, target => "_blank"}, "SOHO"),
		   $q->a({href => $opt{url}{ace_solar_wind}, target => "_blank"}, "ACE"),
                   ")",
		   $q->br,
		   $q->img({class=>"boxed", src => $web_data->{solar_wind}{image}{solar_wind}{file}})
		  );

    $html .= $q->p({style => $image_title_style},
		   $q->a({href => $opt{url}{solar_flare_monitor}, target => "_blank"}, "Solar Flare Monitor"),
		   $q->br,
		   $q->img({class=>"boxed", src => "solar_flare.png", height => 600})
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
    eval { io($opt{file}{web_dir})->mkpath };
    die "ERROR - could not create web directory $opt{file}{web_dir}: $@\n" if $@;

    $html > io("$opt{file}{web_dir}/$opt{file}{web_page}");


    foreach (qw(timeline_png timeline_states)){
	my $in = io("$TaskData/$opt{file}{$_}");
	my $out =io("$opt{file}{web_dir}/$opt{file}{$_}");
	$in > $out if (not -e "$out" or $in->mtime > $out->mtime);
    }

    foreach (qw(title_image blue_paper blue_paper_test
		timeline_js timeline_css vert_line)) {
	my $in = io("$TaskShare/$opt{file}{$_}");
	my $out =io("$opt{file}{web_dir}/$opt{file}{$_}");
	$in > $out if (not -e "$out" or $in->mtime > $out->mtime);
    }


    # Go through each web site where data/images were retrieved
    foreach my $web (values %{$web_content}) {
	next if defined $web->{warn}; # Skip if there was a warning
	foreach my $image (values %{$web->{image}}, values %{$web->{content}}) {
	    next if defined $image->{warn};
	    next unless defined $image->{outfile};

	    # Copy new image file if infile exists and outfile either does not exist
	    # or is older than infile
	    my $in = io($image->{outfile});
	    my $out = io($opt{file}{web_dir} . "/" . $image->{file});
	    next unless -e "$in";
	    if ((not -e "$out") or $in->mtime > $out->mtime) {
		if ($image->{convert}) {
		    my ($status) = run("convert $in $image->{convert} $out");
		    warning($status) if $status;
		} else {
		    $in > $out ;
		}
	    }
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
				-width => '75%',
			       );

    $table->setColStyle(1,"font-size:120%");
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}> " .
		       " Warnings</span>", 'TOP');
    return $table->getTable;
}

####################################################################################
sub make_solar_forecast_table {
####################################################################################
    my $web_data = shift;
    my @table = ([ 'Geophysical Activity', $web_data->{space_weather}{content}{geophys_forecast}{content} ],
		 [ 'Solar Activity', $web_data->{space_weather}{content}{solar_forecast}{content} ]);
    my $table = new HTML::Table(-align => 'center',
				-spacing => 0,
				-padding => 2,
				-rules => 'none',
				-border => 2,
				-data  => \@table,
				-width => '700',
			       );

    $table->setColHead(1);
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}> " .
		       " 3-day Solar-Geophysical Forecast</span>", 'TOP');
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

    my ($ace_date, $ace_p3);
    if (defined $web_data->{ace}{content}{flux}{content}){
        ($ace_date, $ace_p3) = parse_mta_rad_data($start,
                                                  $web_data->{ace}{content}{flux}{content},
                                                  7);
    }
    return '<h2 style="color:red;text-align:center">NO RECENT ACE DATA</h2>' unless (defined $ace_p3 and @{$ace_p3});

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
    $footnotes .= "<br>Grating attenuation not factored into current or 2hr flux numbers";
    $footnotes .= qq{<br><a href="alert_limits.html">RADMON and SOT alert limits information</a>};
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

    my ($hrc_shield_proxy, $hrc_time) = split(' ', io($opt{file}{hrc_shield})->slurp());
    my ($p4gm_proxy, $p4gm_time) = split(' ', io($opt{file}{p4gm})->slurp());
    my ($p41gm_proxy, $p41gm_time) = split(' ', io($opt{file}{p41gm})->slurp());

    my $ephin_date = $snap->{obt}{value} . ' (' .
		  Event::calc_delta_date($snap->{obt}{value}) . ')';
    my $hrc_delta = Event::calc_delta_date($hrc_time);
    my $p4gm_delta = Event::calc_delta_date($p4gm_time);
    my $p41gm_delta = Event::calc_delta_date($p41gm_time);

    # Add a warning above the CXO GOES rates table if the proton data for these
    # is stale.  Since these times are all from the proton/get_hrc data they
    # should be the same, but that implementation could change.
    my $warning = '<h2 style="color:red;text-align:center">';
    if (($CurrentTime - $hrc_time) > 86400){
	$warning .= "HRC proxy data stale<br/>";
    }
    if (($CurrentTime - $p4gm_time) > 86400){
	$warning .= "P4GM data stale<br/>";
    }
    if (($CurrentTime - $p41gm_time) > 86400){
	$warning .= "P41GM data stale<br/>";
    }
    $warning .= "</h2>";

    $val{GOES}{P4GM}  = sprintf("%.2f", $p4gm_proxy);
    $val{GOES}{P41GM} = sprintf("%.2f", $p41gm_proxy);
    $val{GOES}{"HRC shield"} = sprintf("%.0f", $hrc_shield_proxy);
    $val{CXO}{"HRC shield"} = $snap->{hrcshield}{value};
    $val{CXO}{"HRC MCP"} = $snap->{hrcmcp}{value};
    $val{CXO}{P4GM}  = '---';
    $val{CXO}{P41GM} = '---';
    $val{Limit}{"HRC shield"} = 250;
    $val{Limit}{"HRC MCP"} = 30;
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

    my $footnotes = "CXO: from snapshot at $ephin_date<br />";
    $footnotes .= "RadMon: DISABLED<br />" if ($snap->{radmon}{value} ne 'ENAB');
    $footnotes .= "GOES proxies: scaled 15 min average of GOES-16 <br />";
    $footnotes .= "Last avgs at HRC: $hrc_delta &nbsp; P4GM: $p4gm_delta &nbsp; P41GM: $p41gm_delta";
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
    $table->setColStyle(2, "color:#$opt{color}{event_disabled}")
      if ($snap->{radmon}{value} ne 'ENAB');
    $table->setRowStyle(4, "color:#$opt{color}{event_disabled}");

    for $i (2..$n_row) {
	for my $j (2..$n_col) {
	    $table->setCellAlign($i,$j,'RIGHT');
	}
    }
    $table->setCellColSpan($n_row+1, 1, $n_col);
    $table->setCellStyle($n_row+1, 1, $tab_def{footnote_style});
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}> " .
		       " CXO and GOES rates</span>", 'TOP');
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


    return unless /$start\s*/gx;
    while (/\G \s* (\d\d\d\d .+) \s*/gx) {
	my @val = split ' ', $1;
	my $all_ok = 1;
	for my $i (0..$#col) {
	    if ($val[$col[$i]] >= 0) {
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
		      and $evt->tstart - $CurrentTime < $opt{event_table}{display_range}{hours_post}*3600)
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
    my $load_link = ((defined $load_info{URL}) and (defined $load_info{name})) ?
      " (Load: <a href=\"$load_info{URL}/$load_info{name}.php\" target =\"_blank\">$load_info{name}</a>)"
	: " (Load link unavailable)";
    $table->setCaption("<span style=$opt{web_page}{table_caption_style}>"
		       . "Chandra Events"
		       . $load_link
		       . "</span>", 'TOP');
    return $table->getTable;
}

####################################################################################
sub make_snap_table {
####################################################################################
    my $snap = shift;
    my @table;
    my $date = $snap->{obt}{value};
    my $dt = Event::calc_delta_date($snap->{obt}{value});
    my $local_date = Event::calc_local_date($snap->{obt}{value});
    my $delta_time = "&Delta;t = $dt";
    if ($CurrentTime - date2time($date, 'unix') < 100) {
	$delta_time = "from current comm";
    }

    my @row = split "\n", $opt{snap_format};
    my @cols;
    for my $row (@row) {
	@cols = split(/\s*\|\s*/, $row);
	push @table, [ map { defined $snap->{$_} ? "$snap->{$_}{full_name}=$snap->{$_}{value}" : '' } @cols ];
    }

    my @table_col;
    foreach my $j (0..$#cols) {
	my $table_col =  new HTML::Table(-align => 'center',
					 -rules => 'none',
					 -border => 0,
					 -spacing => 0,
					 -padding => 2,
					 -data  => [ map { [ split('=', $table[$_][$j]) ] } (0..$#row) ]
					);
	$table_col->setColStyle(1, 'padding-left: 0cm; padding-right: 0.1cm; text-align:left');
	$table_col->setColStyle(2, 'padding-left: 0.1cm; padding-right: 0cm; text-align:right');
	push @table_col, $table_col->getTable;

    }

    my $footnotes = "Snapshot from $date ($delta_time) ";

    my $table = new HTML::Table(-align => 'center',
			     -rules => 'all',
			     -border => 2,
			     -spacing => 0,
			     -padding => 2,
			     -data  => [[ @table_col ], [$footnotes]],
			    );
    $table->setCellColSpan(2, 1, $#cols+1);
    $table->setCellStyle(2, 1, "font-size:85%");

    $table->setCaption("<span style=$opt{web_page}{table_caption_style}>" .
		       "Key <a href=\"$opt{url}{mta_snapshot}\">Snapshot</a>" .
		       " and <a href=\"$opt{url}{mta_soh}\">SOH</a>" .
		       " Values ($delta_time)" .
		       "</span>", 'TOP');
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
    my $snap  = shift;
    local $_;

    # Make a more convenient hash with SCS state information
    my %scs_state = map { $_ => $snap->{$_}{value} } qw(scs107 scs128 scs129 scs130
							scs131 scs132 scs133 scs_obt);

# The algorithms below require that this code be run frequently (at least every 5 minutes)
# to ensure "seeing" the initial detection of SCS107 in the event of switching in and out
# of EPS subformat

    my $scs107_history_file = "$TaskData/$opt{file}{scs107_history}";
    my $load_running = (grep { $scs_state{"scs$_"} eq 'ACT' } qw(131 132 133)) ? 1 : 0;

    my $scs107_not_inac = ($scs_state{scs107} ne 'INAC') ? 1 : 0;

    # Go in to SCS107 history file and see if scs107 has already been detected
    my $scs107_detected = 0;
    my $scs107_detected_date;
    if (my $scs107_history = io($scs107_history_file)->[-1]) {
	dbg "scs107_history last line = $scs107_history\n";
	my ($date, $history_event) = split /\s*::\s*/, $scs107_history;
	dbg "event = $history_event\n";
	if ($history_event =~ /detected/i) {
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
	$scs107_detected_date = $scs_state{scs_obt};
	"$scs107_detected_date :: SCS107 detected\n" >> io($scs107_history_file);
    } elsif (array_eq(\@a, [0,1,1])) {
	# No action req'd
    } elsif (array_eq(\@a, [1,0,0])) {
	# No action req'd
    } elsif (array_eq(\@a, [1,0,1])) {
	"$scs_state{scs_obt} :: Loads running\n" >> io($scs107_history_file);
	undef $scs107_detected_date;
    } elsif (array_eq(\@a, [1,1,0])) {
	warning("Loads apparently running and SCS107 not INAC at $scs_state{scs_obt}");
	$scs107_detected_date = $scs_state{scs_obt};
	"$scs107_detected_date :: SCS107 detected\n" >> io($scs107_history_file);
    } elsif (array_eq(\@a, [1,1,1])) {
	warning("Loads apparently running and SCS107 not INAC at $scs_state{scs_obt}");
	# (scs107_detected_date already set)
    }

#   get_scs107_runtime($event, $scs107_history_file, \%scs_state) if ($scs107_detected_date);

    warning("SCS 107 detected at $scs107_detected_date") if $scs107_detected_date;
    return $scs107_detected_date;
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
	$type = ($num != 0 and (abs($num) >= 1e5 or abs($num) < 1e-3)) ? 'scientific' : 'normal';
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
