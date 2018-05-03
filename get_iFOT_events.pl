#!/usr/bin/env perl

use strict;
use warnings;

use LWP::UserAgent;
use Data::ParseTable;
use IO::All;
use Config::General;
use Ska::Convert qw(:all);
use Ska::RDB qw(write_rdb);
use Ska::Web;
use Carp;

our $Task     = 'arc';
our $TaskData = "$ENV{SKA_DATA}/$Task";
our $Debug    = 0;
our $CurrentTime = time;	# Use time at start of program for output names

# Global task options
our %opt  = ParseConfig(-ConfigFile => "$TaskData/$Task.cfg");

# iFOT query definitions
our %ifot = ParseConfig(-ConfigFile => "$TaskData/iFOT_queries.cfg");

foreach my $query_id (@{$opt{query_name}}) {
    print "Getting $query_id from iFOT\n" if $Debug;
    # Make HTTP web query for iFOT and do it  (NEED to set timeout and deal with it)
    my $query = make_iFOT_query($query_id);
    print "Query = '$query'\n" if $Debug;
    my ($ifot_user, $ifot_passwd) = Ska::Web::get_user_passwd($ifot{auth_file});
    my $req_tsv = Ska::Web::get_url($query,
                                     user => $ifot_user,
                                     passwd => $ifot_passwd,
                                     timeout => $ifot{timeout}
                                    );
    # Remove trailing whitespace
    $req_tsv =~ s/\s+$//;
    # Split into an array of lines and parse
    my @text = split("\n", $req_tsv);
    # Parse the Table
    my $table = Data::ParseTable::parse_table( \@text, {return_as_hash => 1, field_separator => "\t"});
    my @cols = keys %{$table};
    next unless (defined $table); # Skip empty table

    # Update RDB iFOT archive files (add new one and possibly remove old)
    update_iFOT_archive($query_id, $table, \@cols);
}

##***************************************************************************
sub update_iFOT_archive {
##***************************************************************************
    my $name = shift;
    my $table = shift;
    my $cols = shift;

    # Write data to RDB table named by date
    my $time = $CurrentTime;
    my $date = time2date($time, 'unix_time');
    my $path = "$TaskData/$opt{file}{iFOT_events}/$name";
    io("$path")->mkpath;

    write_rdb("$path/${date}.rdb", $table, @{$cols});
    print "Wrote $path/${date}.rdb\n" if $Debug;

    # Delete tables older than $opt{keep_event_days}
    foreach (glob("$path/*.rdb")) {
	($date) = / ([^\/]+) \.rdb /x;
	my $file_time = date2time($date, 'unix_time');
	unlink if ($time - $file_time > $opt{keep_event_days} * 86400);
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
	return $response->content;
    } else {
	croak $response->status_line;
    }
}


##***************************************************************************
sub make_iFOT_query {
##***************************************************************************
    my $name = shift;
    my %query = ();
    my $http;
    local $_;
    my @query;
    my @query_e;

    # Start with global query defaults
    while (my ($key, $val) = each %{$ifot{default}}) {
	$query{$key} = $val;
    }

    # Next override with options specific to query.  Skip any references
    while (my ($key, $val) = each %{$ifot{query}{$name}}) {
	$query{$key} = $val unless ref $val;
    }

    # Put in the Properties table entries specific to query
    while (my ($table_name, $table) = each %{$ifot{query}{$name}{table}}) {
	my $table_cols = $table->{column} || '';
	$table_cols = join('.', @{$table_cols}) if ref($table_cols) eq 'ARRAY';
	push @query_e, "$table_name.$table_cols";
    }
    $query{e} = join ',', @query_e;

    # Next use values passed to subroutine (highest precedence)
    %query = (%query, @_);

    # Finally make sure there is a tstart, tstop or trange
    unless (($query{tstart} and $query{tstop}) or $query{trange}) {
	$query{tstart} = time2date(time + $query{rel_date_start}*86400, 'unix');
	$query{tstop} = time2date(time + $query{rel_date_stop}*86400, 'unix');
    }
	
    # Now make the actual http query, starting with the http address. 
    $http = "$query{http}?";
    delete $query{http};

    # Put these special parameters in order at the front 
    foreach (qw(r t a size format columns e)) {
	push @query, "$_=$query{$_}" if defined $query{$_};
	delete $query{$_};
    }

    # Then add remaining params in alphabetical order
    push @query, map { "$_=$query{$_}" } sort keys %query;
    $http .= join "&", @query;

    return $http;
}
