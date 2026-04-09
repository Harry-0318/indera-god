const pendingCommands = new Set();
const timers = {};
const INACTIVITY_DELAY = 3000; // 3 seconds

// Initialize sliders
document.querySelectorAll('.joint-slider').forEach(slider => {
    const jointId = slider.closest('.control-card').dataset.joint;
    
    slider.addEventListener('input', (e) => {
        const val = e.target.value;
        const display = slider.parentElement.querySelector('.value-display');
        
        if (jointId === 'M') {
            display.innerText = val;
        } else {
            display.innerText = val + '°';
        }

        queueCommand(jointId, val);
    });
});

function queueCommand(id, value) {
    // Clear existing timer for this joint
    if (timers[id]) {
        clearTimeout(timers[id].timeout);
        clearInterval(timers[id].interval);
    }

    pendingCommands.add(id);
    
    // Start visual feedback (progress bar)
    const indicator = document.getElementById(`queue-${id}`);
    if (indicator) {
        indicator.style.transition = 'none';
        indicator.style.width = '0%';
        
        // Force reflow
        void indicator.offsetWidth;
        
        indicator.style.transition = `width ${INACTIVITY_DELAY/1000}s linear`;
        indicator.style.width = '100%';
    }

    // Set timeout for automatic send
    timers[id] = {
        timeout: setTimeout(() => {
            sendCommand(id, value);
        }, INACTIVITY_DELAY)
    };
}

async function sendCommand(id, value) {
    // Clear state
    if (timers[id]) {
        clearTimeout(timers[id].timeout);
        timers[id] = null;
    }
    pendingCommands.delete(id);
    
    const indicator = document.getElementById(`queue-${id}`);
    if (indicator) {
        indicator.style.transition = 'none';
        indicator.style.width = '0%';
    }

    try {
        const response = await fetch('/send_command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id, value})
        });
        const data = await response.json();
        logCmd(`SENT: ${id}:${value}`);
    } catch (err) {
        logCmd(`ERROR: ${id} failed`);
    }
}

async function sendAllPending() {
    for (const id of Array.from(pendingCommands)) {
        const slider = document.getElementById(`slider-${id}`);
        if (slider) {
            await sendCommand(id, slider.value);
        }
    }
}

async function goHome() {
    try {
        const response = await fetch('/home', { method: 'POST' });
        logCmd("SENT: Home Command");
    } catch (err) {
        logCmd("ERROR: Home command failed");
    }
}

function logCmd(msg) {
    const log = document.getElementById('cmd-log');
    const entry = document.createElement('div');
    entry.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
    log.prepend(entry);
}

// Emergency Stop
document.getElementById('stop-motor').addEventListener('click', () => {
    const slider = document.getElementById('slider-M');
    slider.value = 0;
    slider.dispatchEvent(new Event('input'));
    sendCommand('M', 0);
});

// Controls
document.getElementById('btn-send-all').addEventListener('click', sendAllPending);
document.getElementById('btn-home').addEventListener('click', goHome);

// Keyboard Shortcuts
window.addEventListener('keydown', (e) => {
    if (e.code === 'Space' || e.code === 'Enter') {
        e.preventDefault();
        sendAllPending();
    }
    if (e.code === 'KeyH') {
        goHome();
    }
});
