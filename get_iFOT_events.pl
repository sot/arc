#!/usr/bin/env /proj/sot/ska/bin/perlska

use strict;
use warnings;

use LWP::UserAgent;
use HTML::TableExtract;
use IO::All;
use Config::General;
use Data::Dumper;
use Ska::Convert qw(:all);
use Ska::RDB qw(write_rdb);
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
#    my $req_html = get_iFOT_request($query);
    my $req_html = get_url($query,
			   user => $ifot{authorization}{user},
			   passwd => $ifot{authorization}{passwd},
			   timeout => $ifot{timeout}
			  );

    # Extract the desired table
    my ($table, $cols) = extract_iFOT_table($req_html);
    next unless (defined $table and defined $cols); # Skip empty table

    # Update RDB iFOT archive files (add new one and possibly remove old)
    update_iFOT_archive($query_id, $table, $cols);
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
sub extract_iFOT_table {
##***************************************************************************
    my $req_html = shift;

    # Find the desired iFOT HTML table in the returned result
    my $headers = $ifot{table_match_headers};
    $headers = [ $headers ] unless ref $headers eq 'ARRAY';

    # Find a table with those headers
    my $te = new HTML::TableExtract( headers => $headers );
    $te->parse($req_html);

    # Insist that exactly one table match.  (Use more robust error handling eventually)
    my @ts = $te->table_states;
    warn "ERROR - more than one HTML table had the required headers" if (@ts > 1);
# die "ERROR - HTML table does not have the required headers" if (@ts < 1);
    return if (@ts < 1);  # No data in table

    # Find the table coordinates and now parse the entire table, not just the 
    # spec'd header columns
    my @table_coords = $ts[0]->coords;
    $te = new HTML::TableExtract;
    $te->parse($req_html);
    my $ts = $te->table_state(@table_coords);

    # Get the data into a useful form (hash of arrays)
    my @rows = $ts->rows();
    my @cols = @{$rows[0]};
    map { s/\A [\s<>]+ | [\s<>]+ \Z//gx } @cols;  # clean column names 
    my %data;
    foreach my $i (0 .. $#cols) {
	$data{$cols[$i]} = [ map { $_->[$i] } @rows[1..$#rows] ];
    }

#    return  Ska::HashTable->new(\%data, cols => \@cols);
    return \%data, \@cols;
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
	$query{tstart} = time2date(time + $ifot{query_date_start}*86400, 'unix');
	$query{tstop} = time2date(time + $ifot{query_date_stop}*86400, 'unix');
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

    
