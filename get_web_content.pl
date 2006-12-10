#! /usr/bin/env /proj/sot/ska/bin/perlska

use warnings;
use strict;

use IO::All;
use Config::General;
use Data::Dumper;
use Ska::Convert qw(time2date date2time);
use Ska::Web qw(:all);
use Clone qw(clone);
use Carp;

our $Task     = 'arc';
our $TaskData = "$ENV{SKA_DATA}/$Task";

# Set global current time at beginning of execution
our $CurrentTime = @ARGV ? date2time(shift @ARGV, 'unix') : time;	
our $Debug = 0;
our @warn;	# Global set of processing warnings (warn but don't die)
our %opt = ParseConfig(-ConfigFile => "$TaskData/$Task.cfg");
our %web_content_cfg = ParseConfig(-ConfigFile => "$TaskData/$opt{file}{web_content_cfg}");

our %web_data = %{ clone(\%web_content_cfg) };

while (my ($web_name, $web) = each %web_data) {
    my $url = $web->{url};
    if (exists $web->{add_tstart_tstop}) { # Ugh, custom code for chandra image
	my $tstart = time2date($CurrentTime, 'unix');
	my $tstop = time2date($CurrentTime+228600, 'unix');
	$url .= "&tstart=$tstart&tstop=$tstop";
    }

    my %web_opt = map { $_ => $web->{$_} } grep {not ref($web->{$_})} keys %{$web};
    my ($html, $error) = get_url($url, %web_opt);

    if ($error) {
	warning($web, "$error for web data $web_name ($url)");
	next;
    }

    # Parse each bit of 'content' (i.e. text)
    while (my ($content_name, $content) = each %{$web->{content}}) {
	my ($html_content, $error) = get_html_content($html,
						      url    => $url,
						      %{$content});
	if ($error) {
	    warning($content, "$error for web content $content_name ($url)");
	}

	if ($content->{file}) {
	    $content->{outfile} = "$TaskData/".$content->{file};
	    $html_content > io($content->{outfile});
	} else {
	    $content->{content} = $html_content;
	}
    }

    # Grab each image
    while (my ($image_name, $image) = each %{$web->{image}}) {
	my ($html_content, $error, @image) = get_html_content($html,
							      url    => $url,
							      filter => $image->{filter});

	if ($error) {
	    warning($image, "$error for web image $image_name ($url)");
	}

	$image->{content} = $html_content;

	my $img_file = $image->{file};
	if (@image == 1) {
	    if (length $image[0]->{data} > 100) {
		$image->{outfile} = "$TaskData/$img_file";
		$image[0]->{data} > io($image->{outfile});
	    } else {
	        warning($image, "Retrieved malformed $img_file image")
		  if $image->{warn_bad_image};
	    }
	} else {
	    warning($image, "Did not get exactly one $img_file image");
	}
    }
}

# Save the data.
Config::General->new(\%web_data)->save_file("$TaskData/$opt{file}{web_content}");

print STDERR join("\n", @warn), "\n" if @warn;

##***************************************************************************
sub warning {
##***************************************************************************
    my $h = shift;
    my $msg = shift;
    push @{$h->{warn}}, $msg;
    push @warn, "Warning: $msg";
}

    

