window.onload = initHandlers;

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

function setStateTable(idx) {
    var state = data.states[idx]
    var keys = ['date', 'now_dt','obsid', 'simpos', 'pitch', 'ra', 'dec', 'roll',
                'pcad_mode', 'si', 'si_mode', 'power_cmd', 'ccd_fep', 'vid_clock',
                'fluence', 'p3', 'hrc'];
    for (var i=0; i<keys.length; i++) {
        document.getElementById('tl_' + keys[i]).innerHTML = state[keys[i]];
    }
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

function initHandlers() {
    var acePred = document.getElementById("acePred");
    acePred.onmouseover = function() {
        document.onmousemove = moveHandler;
    }
    acePred.onmouseout = function() {
        document.onmousemove = null;
    }
    now_idx = data['now_idx']
    setStateTable(now_idx);
    document.getElementById('tl_now').innerHTML = data.states[now_idx]['date']
    document.getElementById('tl_track_time').innerHTML = data['track_time']
    document.getElementById('tl_track_dt').innerHTML = data['track_dt']
}
