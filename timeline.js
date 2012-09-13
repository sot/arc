//    document.onmousemove = moveHandler;
window.onload = initHandlers;

function moveHandler(evt) {
    if (!evt) {
	evt = window.event;
    }
    updateTable(evt.clientX, evt.clientY);
}


function setStateTable(idx) {
    var states = data.states
    var table_date = document.getElementById("table_date");
    var table_obsid = document.getElementById("table_obsid");
    table_date.innerHTML = states[idx].date;
    table_obsid.innerHTML = states[idx].obsid;
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
