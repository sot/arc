#----------------------------------------------------------------------------------
#----------------------------------------------------------------------------------
package Snap;
#----------------------------------------------------------------------------------
#----------------------------------------------------------------------------------
use warnings;
use strict;
use IO::All;
use Data::Dumper;
use Ska::Convert qw(time2date date2time);

our $CurrentTime;
our @warn;
our $snap_definition;		# Global hash ref specifying how to parse snapshot

1;

####################################################################################
sub get_snap {
#
# Get Chandra snapshot and parse.  Failing to do this is fatal since processing
# really needs an obsid
####################################################################################
    my $snarc_dir = shift;
    my @snap_files = @{ shift() };
    my $snap;			# Latest snapshot as a string
    my @snarc;			# Recent snapshots (array of hashes in reverse time order)
    my %snap;			# Final snapshot parsed into a hash

    local $_;

    # Global warnings concerning missing files etc
    @warn = ();

    # First just get the latest Chandra snapshot (as a string)
  SNAPFILE: foreach my $file (@snap_files) {
	if (-r $file) {
	    $snap < io($file);
	    last SNAPFILE;
	} else {
	    my $msg = "Could not find snapshot file $file";
	    push @warn, $msg;
	    print STDERR "Error - $msg\n";
	}
    }

    # Parse the latest snapshot.  In general this does not have correct SCS state info
    # (which is only available in EPS subformat)
    %snap = parse_snap($snap);

    # Get all the snapshots from the last few days in reverse time order. 
    # If get_snap_archive fails then just use the single most recent snap
    my $snarc_ref = get_snap_archive($snarc_dir) || [ { %snap } ];
    
    # Use get_scs_states to determine the correct SCS state values 
    my %scs_state = get_scs_states($snarc_ref);

    # Copy SCS state values into the final snapshot hash
    $snap{$_}{value} = $scs_state{$_} foreach qw(scs107 scs128 scs129 scs130 scs_obt);

    unless (defined $snap{obsid}{value}) {
	my $msg = "Error - no obsid parsed from snapshot string: \n'$snap'\n";
	push @warn, $msg;
	print STDERR $msg;
    }

    return \@warn, %snap;
}

####################################################################################
sub parse_snap {
# Parse the snapshot string into desired key/value pairs
####################################################################################
    local $_;
    my $snap = shift;
    my %snap;

    $snap =~ s/\s+/ /g;
    while (my ($name, $delim) = each %{$snap_definition}) {
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
sub get_snap_archive {
####################################################################################
    my $snarc_dir = shift;
    local $_;
    my $snap_archive;
    foreach (glob "${snarc_dir}.???????") {
	next unless /\d{7}\Z/;	# Make sure it ends with something like 2005128
	$snap_archive .= io($_)->slurp; # can't use << because of emacs parsing
    }

    unless ($snap_archive) {
	my $msg = "No files in snapshot archive dir $snarc_dir found";
	push @warn, $msg;
	print STDERR "$msg\n";
	return;
    }
	
    $snap_archive =~ s/<.*?>//g;	# Do the stupidest possible HTML tag removal.
				# since it's fast and works for snarc files
    # See HTML::FormatText for the "right" way to do it,  except that the damn 
    # thing doesn't work for <pre> with HTML formatting tags!
 
    # Split on the UTC key, but then put it back into each snapshot
    my @snap_archive = map { "UTC $_" } split /^UTC/m, $snap_archive;

    my @snap = map { { parse_snap($_) } } @snap_archive;
    @snap = reverse grep { defined $_->{utc}{value} } @snap;

    return \@snap;
}

####################################################################################
sub get_scs_states {
####################################################################################
    local $_;
    my $snarc_ref = shift;

    my %scs_state;
    my @snap;
    my $have_scs_states;

    # Most recent state of SCS slots 107, 128, 129, 130.  But back up as far
    # as possible in time to get the earliest detection of SCS107 run.

SNAP: for my $snap (@{$snarc_ref}) {
	# Don't use a snapshot newer than CurrentTime (mostly relevant for testing)
	next SNAP unless date2time($snap->{obt}{value}, 'unix') < $CurrentTime;

	$have_scs_states = defined $scs_state{scs107};
	if ($snap->{format}{value} =~ /_eps/i) {
	    my %curr_scs_state = map { $_ => $snap->{$_}{value} } qw(scs107 scs128 scs129 scs130 obt utc);
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

    unless ($have_scs_states) {
	@scs_state{qw(scs107 scs128 scs129 scs130)} = qw(??? ??? ??? ???);
	@scs_state{qw(obt utc)} = ($CurrentTime, $CurrentTime);
    }
	  
    # Clean up %scs_state a bit so it can be easily merged with %snap to force
    # "good" values of the SCS status flags, without clobbering the existing OBT,UTC
    for (qw(obt utc)) {
	$scs_state{"scs_$_"} = $scs_state{$_};
	delete $scs_state{$_};
    }

    return %scs_state;
}

##***************************************************************************
sub set_CurrentTime {
##***************************************************************************
    $CurrentTime = shift;
}

####################################################################################
sub set_snap_definition {
####################################################################################
    $snap_definition = shift;
}

