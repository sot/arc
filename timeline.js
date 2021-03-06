// window.onload = initTimeLineHandlers;

function moveHandler(evt) {
    if (!evt) var evt = window.event;
    xy = getXY(evt)
    updateTable(xy[0], xy[1]);
}

function getXY(e) {
    var posx = 0;
    var posy = 0;
    if (e.pageX || e.pageY) {
	posx = e.pageX;
	posy = e.pageY;
    }
    else if (e.clientX || e.clientY) {
	posx = e.clientX + document.body.scrollLeft
	    + document.documentElement.scrollLeft;
	posy = e.clientY + document.body.scrollTop
	    + document.documentElement.scrollTop;
    }
    return [posx, posy]
}

function spanColor(val, color) {
    return '<span style="font-weight:bold;color:' + color + '">' + val + '</span>'
}

function setNAToRed(val) {
    if (val == 'N/A') {
        val = spanColor(val, 'red')
    }
    return val
}

function setStateTable(idx) {
    var state = data.states[idx]
    var keys = ['date', 'now_dt', 'simpos', 'pitch', 'ra', 'dec', 'roll',
                'pcad_mode', 'si_mode', 'power_cmd', 'ccd_fep', 'vid_clock',
                'fluence', 'p3', 'hrc'];
    for (var i=0; i<keys.length; i++) {
        document.getElementById('tl_' + keys[i]).innerHTML = setNAToRed(state[keys[i]]);
    }

    if (data['p3_avg_now'] == 'N/A') {
        document.getElementById('tl_fluence').innerHTML = spanColor(state['fluence'], 'red')
    }

    document.getElementById('tl_obsid').innerHTML =
        '<a target="_blank" href="https://icxc.harvard.edu/cgi-bin/mp/target_param.cgi?'
        + state['obsid'] + '">'
        + state['obsid'] + '</a>';

    if (state['simpos'] > 0) {
        var color = 'blue'
    } else {
        var color = 'red'
    }
    document.getElementById('tl_si').innerHTML = spanColor(state['si'], color)

    if (state['hetg'] == 'INSR') {
        var grating = 'HETG';
    } else if (state['letg'] == 'INSR') {
        var grating = 'LETG';
    } else {
        var grating = 'NONE';
    }
    document.getElementById('tl_grating').innerHTML = grating
}

function updateTable(xPos, yPos) {
    var acePred = document.getElementById("acePred");
    var xleft = acePred.offsetLeft;
    var ytop = acePred.offsetTop;
    var x = (xPos - xleft) / acePred.width
    var y = (yPos - ytop) / acePred.height
    var ax_x = data.ax_x
    var ax_y = [1 - data.ax_y[1], 1 - data.ax_y[0]]
    if ((x > ax_x[0]) && (x < ax_x[1]) && (y > ax_y[0]) && (y < ax_y[1])) {
        var idx = Math.floor((x - ax_x[0]) / (ax_x[1] - ax_x[0]) * data.states.length);
        setStateTable(idx);
        moveVerticalLine(xPos, ytop + ax_y[0] * acePred.height)
    }
}

function moveVerticalLine(x, y) {
    var line = document.getElementById("vertLine");
    line.style.left = x + "px";
    line.style.top = y + "px";
    line.style.visibility = "visible";
}

function initTimeLineHandlers() {
    var acePred = document.getElementById("acePred");
    acePred.onmouseover = function() {
        document.onmousemove = moveHandler;
    }
    acePred.onmouseout = function() {
        document.onmousemove = null;
    }
    now_idx = data['now_idx']
    setStateTable(now_idx, data);
    document.getElementById('tl_now').innerHTML = data['now_date']
    document.getElementById('tl_track_time').innerHTML = data['track_time']
    document.getElementById('tl_track_dt').innerHTML = data['track_dt']
    document.getElementById('tl_track_station').innerHTML = data['track_station']
    document.getElementById('tl_track_activity').innerHTML = data['track_activity']
    document.getElementById('tl_p3_avg_now').innerHTML = setNAToRed(data['p3_avg_now'])
    document.getElementById('tl_p3_now').innerHTML = setNAToRed(data['p3_now'])
    document.getElementById('tl_hrc_now').innerHTML = data['hrc_now']

}
