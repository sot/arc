window.onload = initHandlers;

function moveHandler(evt) {
    if (!evt) {
	evt = window.event;
    }
    updateTable(evt.clientX, evt.clientY);
}


function setStateTable(idx) {
    var state = data.states[idx]
    document.getElementById("tl_date").innerHTML = state.date;
    document.getElementById("tl_obsid").innerHTML = state.obsid;
    document.getElementById("tl_simpos").innerHTML = state.simpos;
    document.getElementById("tl_pitch").innerHTML = state.pitch;
    document.getElementById("tl_ra").innerHTML = state.ra;
    document.getElementById("tl_dec").innerHTML = state.dec;
    document.getElementById("tl_roll").innerHTML = state.roll;
    document.getElementById("tl_pcad_mode").innerHTML = state.pcad_mode;
    document.getElementById("tl_si_mode").innerHTML = state.si_mode;
    document.getElementById("tl_power_cmd").innerHTML = state.power_cmd;
    document.getElementById("tl_ccd_count").innerHTML = state.ccd_count;
    document.getElementById("tl_fep_count").innerHTML = state.fep_count;
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
}
