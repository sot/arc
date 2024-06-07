#! /usr/bin/env perl

use warnings;
use strict;

use Try::Tiny qw(try catch);
use IO::All;
use Config::General qw(ParseConfig);
use Net::Netrc;
use Data::Dumper;
use Ska::Convert qw(time2date date2time);
use Ska::Web;
use Clone qw(clone);
use Carp;
use POSIX qw(strftime);

our $Task     = 'arc3';
our $TaskData = "$ENV{SKA_DATA}/$Task";
our $TaskShare = "$ENV{SKA_SHARE}/$Task";

# Set global current time at beginning of execution
our $CurrentTime = @ARGV ? date2time(shift @ARGV, 'unix') : time;	
our $Debug = 0;
our @warn;	# Global set of processing warnings (warn but don't die)
our %opt = ParseConfig(-ConfigFile => "$TaskShare/$Task.cfg");
our %web_content_cfg = ParseConfig(-ConfigFile => "$TaskShare/$opt{file}{web_content_cfg}");

our %web_data = %{ clone(\%web_content_cfg) };

while (my ($web_name, $web) = each %web_data) {
    my $url = $web->{url};
    if (exists $web->{add_tstart_tstop}) { # Ugh, custom code for chandra image
	my $tstart = time2date($CurrentTime, 'unix');
	my $tstop = time2date($CurrentTime+228600, 'unix');
	$url .= "&tstart=$tstart&tstop=$tstop";
    }

    my %web_opt = map { $_ => $web->{$_} } grep {not ref($web->{$_})} keys %{$web};

    # Get username and password from netrc if required
    if (defined $web_opt{netrc}) {
	my $netrc = Net::Netrc->lookup($web_opt{netrc});
	$web_opt{user} = $netrc->login;
	$web_opt{passwd} = $netrc->password;
    }
        
    my ($html, $error, $header) = Ska::Web::get_url($url, %web_opt);

    if ($error) {
	warning($web, "$error for web data $web_name ($url)");
	next;
    }

    # Parse each bit of 'content' (i.e. text)
    while (my ($content_name, $content) = each %{$web->{content}}) {
	my ($html_content, $error) = Ska::Web::get_html_content($html,
						      url    => $url,
						      %{$content});
	if ($error) {
	    warning($content, "$error for web content $content_name ($url)");
	}

	if ($content->{file}) {
	    $content->{outfile} = "$TaskData/".$content->{file};
	    $html_content > io($content->{outfile});
            if (defined $header->last_modified){
                utime($header->last_modified, $header->last_modified, $content->{outfile});
            }
	} else {
	    $content->{content} = $html_content;
	}
    }

    # Grab each image
    while (my ($image_name, $image) = each %{$web->{image}}) {
        my $tries = $image->{tries} || 1;
        my $img_file = $image->{file};
        $image->{outfile} = "$TaskData/$img_file";
        my $got_image = 0;

        if (exists $web->{add_date}) { # Ugh, custom code for magnetogram
            my $src = $image->{filter}{src};
            my $year = strftime "%Y", gmtime;
            my $mon = strftime "%b", gmtime;
            my $day = strftime "%e", gmtime;
            $mon = lc($mon);
            $day =~ s/^\s+//;
            my $str = "$year/$mon$day\_$year\_mag";
            $image->{filter}{src} = $src ~=  s/mag/$str/r;
        }

      TRY: for my $try (1 .. $tries) {
            try {
                my ($html_content, $error, @image) = Ska::Web::get_html_content(
                    $html,
                    url    => $url,
                    filter => $image->{filter});
                if ($error) {
                    die $error;
                }
                if (@image != 1) {
                    die "Did not get exactly one $img_file image";
                }
                if ((length $image[0]->{data}) < 100) {
                    die "Retrieved malformed $img_file image after $tries try(s)";
                }
                $image->{content} = $html_content;
                $image[0]->{data} > io($image->{outfile});
                utime($image[0]->{header}->last_modified,
                      $image[0]->{header}->last_modified,
                      $image->{outfile});
                $got_image = 1;
            }
            catch {
                if ($try < $tries){
                    sleep($image->{'sleep'} || 10)
                }
                if (not defined $image->{warn_age_hours} and
                        $image->{warn_bad_image} and $try == $tries) {
                    warning($image, $_);
                }
            };
            last TRY if $got_image == 1;
        }
        if (($got_image == 0) and (defined $image->{warn_age_hours})){
            if (((-M $image->{outfile}) * 24) > $image->{warn_age_hours}){
                warning(
                    $image,
                    "Did not get $img_file and more than $image->{warn_age_hours} hours old");
            }
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
