#!/usr/bin/env perl

# copy newest dated files from the get_iFOT_events directory to a iFOT_time_machine directory
# use mercurial to "check in" change
# the iFOT_time_machine mercurial repository can then be used to get the iFOT status
# at any time with something like:
#
# hg pull -u $ska/data/arc3/iFOT_time_machine
# hg update --date " < <date-time> "



use strict;
use warnings;
use Config::General qw(ParseConfig);
use Carp;
use Ska::Run qw( run );
use Ska::Convert qw( time2date );
use File::chdir;
use Getopt::Long;
use FindBin;


my $CurrentTime = time;	# Use time at start of program for output names
my $date = time2date($CurrentTime, 'unix_time');

# Global task options
my $config_file = File::Spec->catfile($FindBin::Bin, "..", 'data', "arc3.cfg");
my %opt  = ParseConfig(-ConfigFile => "$config_file");

my %cmd_opt = ( verbose => 0 );
my $arc_data_dir;
my $time_machine_dir;
GetOptions( \%cmd_opt,
        "arc-data-dir=s" => \$arc_data_dir,
        "time-machine-dir=s" => \$time_machine_dir,
	    "verbose!");

# Make a directory if needed
unless (-d $time_machine_dir) {
    mkdir $time_machine_dir or croak("Failed to create directory $time_machine_dir: $!");
}

foreach my $query_id (@{$opt{query_name}}) {
    # find arc iFOT file for query
    my $source_path = "${arc_data_dir}/$opt{file}{iFOT_events}/${query_id}";
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


# Git commit and tag logic in Perl
{
    local $CWD = $time_machine_dir;
    # Initialize git repo if not present
    unless (-d "$time_machine_dir/.git") {
        run("git init", loud => $cmd_opt{verbose});
        run("git add .", loud => $cmd_opt{verbose});
        run("git commit --allow-empty -a -m 'Initial commit'", loud => $cmd_opt{verbose});
    }
    # Add and commit all changes, then tag with current date
    run("git add .", loud => $cmd_opt{verbose});
    run("git commit --allow-empty -a -m 'Update time machine files'", loud => $cmd_opt{verbose});
    my $tag = `date '+%Y-%m-%d'`;
    chomp $tag;
    run("git tag $tag", loud => $cmd_opt{verbose});
}


