#!/usr/bin/env perl

# copy newest dated files from the get_iFOT_events directory to a iFOT_time_machine directory
# use mercurial to "check in" change
# the iFOT_time_machine mercurial repository can then be used to get the iFOT status
# at any time with something like:
# 
# hg pull -u $ska/data/arc/iFOT_time_machine
# hg update --date " < <date-time> "



use strict;
use warnings;
use Config::General qw(ParseConfig);
use Carp;
use Ska::Run qw( run );
use Ska::Convert qw( time2date );
use File::chdir;
use Getopt::Long;

my $Task     = 'arc';
my $TaskData = "$ENV{SKA_DATA}/$Task";
my $TaskShare = "$ENV{SKA_SHARE}/$Task";
my $CurrentTime = time;	# Use time at start of program for output names
my $date = time2date($CurrentTime, 'unix_time');
my $time_machine_dir = "$TaskData/iFOT_time_machine";

# Global task options
my %opt  = ParseConfig(-ConfigFile => "$TaskShare/$Task.cfg");

my %cmd_opt = ( verbose => 0 );
GetOptions( \%cmd_opt,
	    "verbose!");

foreach my $query_id (@{$opt{query_name}}) {
    # find arc iFOT file for query
    my $source_path = "${TaskData}/$opt{file}{iFOT_events}/${query_id}";
    my @query_files = sort(glob("${source_path}/*.rdb"));
    croak("No RDB files found in $source_path") unless scalar(@query_files);
    my $recent_file = $query_files[-1];

    # copy file to time machine directory
    if ($cmd_opt{verbose}){
	print "Syncing ${time_machine_dir}/${query_id}.rdb \n";
    }
    my $status = run("rsync -aruvz $recent_file ${time_machine_dir}/${query_id}.rdb");
    if ($status){
	croak("failed to copy over $recent_file \n");
    }
}

# have mercurial commit the changes as needed
{
    local $CWD = $time_machine_dir;
    run("hg commit -m \"${date}\"", loud => $cmd_opt{verbose});
}
