const INACTIVITY_DELAY = 3000;
const pendingCommands = new Set();
const timers = {};

let positionsCache = {};
let workflowsCache = {};
let automationsCache = [];
let currentWorkflowSequence = [];
let editingAutomationId = null;
let sensorPollHandle = null;

function logCmd(message) {
    const log = document.getElementById('cmd-log');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    log.prepend(entry);
}

function setStatus(text, isHealthy = true) {
    document.getElementById('status-text').textContent = text;
    document.getElementById('serial-status').classList.toggle('offline', !isHealthy);
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.message || 'Request failed');
    }

    return data;
}

function updateSliderDisplay(slider) {
    const id = slider.closest('.control-card').dataset.joint;
    const display = slider.parentElement.querySelector('.value-display');
    if (!display) {
        return;
    }

    display.innerText = id === 'M' ? slider.value : `${slider.value}°`;
}

function applyAnglesToUi(angles) {
    Object.entries(angles).forEach(([id, value]) => {
        const slider = document.getElementById(`slider-${id}`);
        if (!slider) {
            return;
        }

        slider.value = value;
        updateSliderDisplay(slider);
    });
}

function queueCommand(id, value) {
    if (timers[id]) {
        clearTimeout(timers[id].timeout);
    }

    pendingCommands.add(id);

    const indicator = document.getElementById(`queue-${id}`);
    if (indicator) {
        indicator.style.transition = 'none';
        indicator.style.width = '0%';
        void indicator.offsetWidth;
        indicator.style.transition = `width ${INACTIVITY_DELAY / 1000}s linear`;
        indicator.style.width = '100%';
    }

    timers[id] = {
        timeout: setTimeout(() => {
            sendCommand(id, value);
        }, INACTIVITY_DELAY)
    };
}

async function sendCommand(id, value) {
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
        await requestJson('/send_command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id, value})
        });
        logCmd(`SENT ${id}:${value}`);
        setStatus('System ready', true);
    } catch (error) {
        logCmd(`ERROR ${id}:${value} -> ${error.message}`);
        setStatus('Serial error', false);
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
        await requestJson('/home', {method: 'POST'});
        logCmd('HOME command sent');
    } catch (error) {
        logCmd(`ERROR home -> ${error.message}`);
    }
}

async function loadPositions() {
    positionsCache = await requestJson('/positions');
    renderPositions();
    renderPositionBlocks();
}

function renderPositions() {
    const container = document.getElementById('saved-positions');
    container.innerHTML = '';

    if (Object.keys(positionsCache).length === 0) {
        container.innerHTML = '<div class="empty-msg">No saved positions yet.</div>';
        return;
    }

    Object.entries(positionsCache).forEach(([name, angles]) => {
        const item = document.createElement('div');
        item.className = 'stack-item';
        const coordStr = Object.entries(angles).map(([joint, value]) => `${joint}:${value}`).join(' ');

        item.innerHTML = `
            <div>
                <div class="item-title">${name}</div>
                <div class="item-subtitle">${coordStr}</div>
            </div>
            <div class="item-actions">
                <button class="btn-success compact" onclick="goToPosition('${name.replace(/'/g, "\\'")}')">Go</button>
                <button class="btn-ghost compact" onclick="deletePosition('${name.replace(/'/g, "\\'")}')">Delete</button>
            </div>
        `;
        container.appendChild(item);
    });
}

function renderPositionBlocks() {
    const blockList = document.getElementById('available-positions');
    blockList.innerHTML = '';

    const homeBlock = document.createElement('button');
    homeBlock.className = 'wf-block special';
    homeBlock.textContent = 'HOME';
    homeBlock.addEventListener('click', () => addMoveStep('HOME'));
    blockList.appendChild(homeBlock);

    Object.keys(positionsCache).forEach(name => {
        const block = document.createElement('button');
        block.className = 'wf-block';
        block.textContent = name;
        block.addEventListener('click', () => addMoveStep(name));
        blockList.appendChild(block);
    });
}

async function saveCurrentPosition() {
    const nameInput = document.getElementById('pos-name');
    const name = nameInput.value.trim();

    if (!name) {
        alert('Enter a position name.');
        return;
    }

    const angles = {};
    document.querySelectorAll('.joint-slider').forEach(slider => {
        const id = slider.closest('.control-card').dataset.joint;
        angles[id] = slider.value;
    });

    await requestJson('/save_position', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, angles})
    });

    nameInput.value = '';
    await loadPositions();
    logCmd(`POSITION saved -> ${name}`);
}

async function deletePosition(name) {
    if (!confirm(`Delete position '${name}'?`)) {
        return;
    }

    await requestJson('/delete_position', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name})
    });

    await loadPositions();
    logCmd(`POSITION deleted -> ${name}`);
}

function getHomeAngles() {
    return {'B': 90, 'S': 90, 'E': 160, 'W': 90, 'R': 90, 'G': 180, 'M': 0};
}

async function goToPosition(name) {
    const angles = name === 'HOME' ? getHomeAngles() : positionsCache[name];
    if (!angles) {
        return;
    }

    applyAnglesToUi(angles);
    logCmd(`MOVE -> ${name}`);

    for (const id of ['B', 'S', 'E', 'W', 'R', 'G', 'M']) {
        if (angles[id] !== undefined) {
            await sendCommand(id, angles[id]);
            await new Promise(resolve => setTimeout(resolve, 200));
        }
    }
}

function addMoveStep(positionName) {
    currentWorkflowSequence.push({type: 'move', name: positionName});
    renderWorkflowSequence();
}

function addWaitStep() {
    const duration = parseFloat(document.getElementById('wait-duration').value);
    if (!duration || duration <= 0) {
        alert('Wait duration must be greater than 0.');
        return;
    }

    currentWorkflowSequence.push({type: 'wait', duration});
    renderWorkflowSequence();
}

function removeStep(index) {
    currentWorkflowSequence.splice(index, 1);
    renderWorkflowSequence();
}

function renderWorkflowSequence() {
    const container = document.getElementById('wf-sequence');
    container.innerHTML = '';

    if (currentWorkflowSequence.length === 0) {
        container.innerHTML = '<div class="empty-msg">Add move or wait blocks to build a workflow.</div>';
        return;
    }

    currentWorkflowSequence.forEach((step, index) => {
        const item = document.createElement('div');
        item.className = `sequence-item ${step.type}`;
        item.id = `wf-step-${index}`;
        item.innerHTML = `
            <div>
                <div class="item-title">${step.type === 'move' ? `Move to ${step.name}` : `Wait ${step.duration}s`}</div>
                <div class="item-subtitle">${step.type === 'move' ? 'Position step' : 'Delay step'}</div>
            </div>
            <button class="btn-text" onclick="removeStep(${index})">Remove</button>
        `;
        container.appendChild(item);
    });
}

async function saveWorkflow() {
    const nameInput = document.getElementById('wf-name');
    const name = nameInput.value.trim();

    if (!name || currentWorkflowSequence.length === 0) {
        alert('Enter a workflow name and add at least one step.');
        return;
    }

    await requestJson('/save_workflow', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name, steps: currentWorkflowSequence})
    });

    nameInput.value = '';
    currentWorkflowSequence = [];
    renderWorkflowSequence();
    await loadWorkflows();
    logCmd(`WORKFLOW saved -> ${name}`);
}

async function loadWorkflows() {
    workflowsCache = await requestJson('/workflows');
    renderWorkflowLibrary();
    populateWorkflowSelect();
}

function renderWorkflowLibrary() {
    const container = document.getElementById('wf-list');
    container.innerHTML = '';

    const names = Object.keys(workflowsCache);
    if (names.length === 0) {
        container.innerHTML = '<div class="empty-msg">No saved workflows yet.</div>';
        return;
    }

    names.forEach(name => {
        const item = document.createElement('div');
        item.className = 'stack-item';
        item.innerHTML = `
            <div>
                <div class="item-title">${name}</div>
                <div class="item-subtitle">${workflowsCache[name].length} steps</div>
            </div>
            <div class="item-actions">
                <button class="btn-success compact" onclick="executeWorkflowByName('${name.replace(/'/g, "\\'")}')">Run</button>
                <button class="btn-ghost compact" onclick="deleteWorkflow('${name.replace(/'/g, "\\'")}')">Delete</button>
            </div>
        `;
        container.appendChild(item);
    });
}

function populateWorkflowSelect() {
    const select = document.getElementById('automation-workflow');
    select.innerHTML = '';

    Object.keys(workflowsCache).forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });
}

async function runWorkflow(sequence = null) {
    const steps = sequence || currentWorkflowSequence;
    if (steps.length === 0) {
        return;
    }

    logCmd('WORKFLOW started');

    for (let index = 0; index < steps.length; index += 1) {
        const step = steps[index];
        const element = document.getElementById(`wf-step-${index}`);
        if (element) {
            element.classList.add('active');
        }

        if (step.type === 'move') {
            await goToPosition(step.name);
        } else if (step.type === 'wait') {
            logCmd(`WAIT ${step.duration}s`);
            await new Promise(resolve => setTimeout(resolve, step.duration * 1000));
        }

        if (element) {
            element.classList.remove('active');
        }
    }

    logCmd('WORKFLOW complete');
}

async function executeWorkflowByName(name) {
    const steps = workflowsCache[name];
    if (!steps) {
        return;
    }

    await runWorkflow(steps);
}

async function deleteWorkflow(name) {
    if (!confirm(`Delete workflow '${name}'?`)) {
        return;
    }

    await requestJson('/delete_workflow', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name})
    });

    await loadWorkflows();
    logCmd(`WORKFLOW deleted -> ${name}`);
}

function resetAutomationForm() {
    editingAutomationId = null;
    document.getElementById('automation-name').value = '';
    document.getElementById('automation-threshold').value = 6;
    document.getElementById('automation-delay').value = 1500;
    document.getElementById('automation-cooldown').value = 5000;
    document.getElementById('automation-action').value = 'stop_motor';
    document.getElementById('automation-enabled').checked = true;
    document.getElementById('automation-form-mode').textContent = 'New Rule';
    syncAutomationWorkflowVisibility();
}

function syncAutomationWorkflowVisibility() {
    const action = document.getElementById('automation-action').value;
    const field = document.getElementById('automation-workflow-field');
    field.classList.toggle('hidden', action !== 'run_workflow');
}

function fillAutomationForm(automation) {
    editingAutomationId = automation.id;
    document.getElementById('automation-name').value = automation.name;
    document.getElementById('automation-threshold').value = automation.threshold_cm;
    document.getElementById('automation-delay').value = automation.delay_ms;
    document.getElementById('automation-cooldown').value = automation.cooldown_ms;
    document.getElementById('automation-action').value = automation.action_type;
    document.getElementById('automation-enabled').checked = automation.enabled;
    populateWorkflowSelect();
    if (automation.workflow_name) {
        document.getElementById('automation-workflow').value = automation.workflow_name;
    }
    document.getElementById('automation-form-mode').textContent = 'Editing Rule';
    syncAutomationWorkflowVisibility();
}

async function loadAutomations() {
    automationsCache = await requestJson('/automations');
    renderAutomations();
}

function automationActionLabel(automation) {
    if (automation.action_type === 'run_workflow') {
        return `Run workflow: ${automation.workflow_name}`;
    }
    if (automation.action_type === 'home_arm') {
        return 'Send home command';
    }
    return 'Send M:0';
}

function renderAutomations() {
    const container = document.getElementById('automation-list');
    container.innerHTML = '';

    if (automationsCache.length === 0) {
        container.innerHTML = '<div class="empty-msg">No automation rules yet.</div>';
        return;
    }

    automationsCache.forEach(automation => {
        const runtime = automation.runtime || {};
        const statusText = runtime.is_pending
            ? 'Pending'
            : runtime.cooldown_remaining_ms > 0
                ? `Cooldown ${Math.ceil(runtime.cooldown_remaining_ms / 1000)}s`
                : automation.enabled ? 'Armed' : 'Disabled';

        const item = document.createElement('div');
        item.className = 'automation-card';
        item.innerHTML = `
            <div class="automation-card-top">
                <div>
                    <div class="item-title">${automation.name}</div>
                    <div class="item-subtitle">If distance < ${automation.threshold_cm} cm, wait ${automation.delay_ms} ms</div>
                </div>
                <span class="runtime-pill ${automation.enabled ? 'enabled' : 'disabled'}">${statusText}</span>
            </div>
            <div class="automation-card-body">
                <div class="meta-line">Action: ${automationActionLabel(automation)}</div>
                <div class="meta-line">Cooldown: ${automation.cooldown_ms} ms</div>
                <div class="meta-line">Last result: ${runtime.last_result || 'No runs yet'}</div>
            </div>
            <div class="item-actions">
                <button class="btn-ghost compact" onclick="toggleAutomation('${automation.id}')">${automation.enabled ? 'Disable' : 'Enable'}</button>
                <button class="btn-ghost compact" onclick="editAutomation('${automation.id}')">Edit</button>
                <button class="btn-ghost compact" onclick="deleteAutomation('${automation.id}')">Delete</button>
            </div>
        `;
        container.appendChild(item);
    });
}

async function saveAutomation() {
    const payload = {
        id: editingAutomationId,
        name: document.getElementById('automation-name').value.trim(),
        threshold_cm: parseFloat(document.getElementById('automation-threshold').value),
        delay_ms: parseInt(document.getElementById('automation-delay').value, 10),
        cooldown_ms: parseInt(document.getElementById('automation-cooldown').value, 10),
        action_type: document.getElementById('automation-action').value,
        workflow_name: document.getElementById('automation-workflow').value,
        enabled: document.getElementById('automation-enabled').checked
    };

    await requestJson('/save_automation', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });

    resetAutomationForm();
    await loadAutomations();
    logCmd(`AUTOMATION saved -> ${payload.name}`);
}

function editAutomation(id) {
    const automation = automationsCache.find(item => item.id === id);
    if (automation) {
        fillAutomationForm(automation);
    }
}

async function toggleAutomation(id) {
    const automation = automationsCache.find(item => item.id === id);
    if (!automation) {
        return;
    }

    const payload = {
        ...automation,
        enabled: !automation.enabled
    };

    await requestJson('/save_automation', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });

    await loadAutomations();
    logCmd(`AUTOMATION ${payload.enabled ? 'enabled' : 'disabled'} -> ${payload.name}`);
}

async function deleteAutomation(id) {
    const automation = automationsCache.find(item => item.id === id);
    if (!automation) {
        return;
    }

    if (!confirm(`Delete automation '${automation.name}'?`)) {
        return;
    }

    await requestJson('/delete_automation', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id})
    });

    if (editingAutomationId === id) {
        resetAutomationForm();
    }

    await loadAutomations();
    logCmd(`AUTOMATION deleted -> ${automation.name}`);
}

function formatSensorTime(timestamp) {
    if (!timestamp) {
        return '--';
    }

    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) {
        return timestamp;
    }

    return date.toLocaleTimeString();
}

async function pollSensorState() {
    try {
        const state = await requestJson('/sensor_state');
        const distance = state.distance_cm;
        const distanceText = typeof distance === 'number' ? `${distance.toFixed(1)} cm` : '-- cm';

        document.getElementById('distance-pill').textContent = distanceText;
        document.getElementById('distance-reading').textContent = typeof distance === 'number' ? distance.toFixed(1) : '--';
        document.getElementById('distance-detail').textContent = typeof distance === 'number'
            ? distance < 6 ? 'Inside 6 cm risk band.' : 'Outside immediate stop band.'
            : 'Waiting for sensor data.';
        document.getElementById('sensor-mode').textContent = state.status || 'Idle';
        document.getElementById('sensor-last-updated').textContent = formatSensorTime(state.last_updated);
        document.getElementById('sensor-raw-line').textContent = state.last_raw || '--';

        const pendingCount = (state.automations || []).filter(item => item.runtime && item.runtime.is_pending).length;
        document.getElementById('pending-automation-count').textContent = String(pendingCount);

        automationsCache = state.automations || [];
        renderAutomations();

        const healthy = state.status && !String(state.status).startsWith('error') && state.status !== 'arduino_1_not_connected';
        setStatus(healthy ? 'Sensor online' : state.status, healthy);
    } catch (error) {
        setStatus('Backend unreachable', false);
    }
}

function wireControls() {
    document.querySelectorAll('.joint-slider').forEach(slider => {
        slider.addEventListener('input', event => {
            updateSliderDisplay(event.target);
            const jointId = slider.closest('.control-card').dataset.joint;
            queueCommand(jointId, event.target.value);
        });
    });

    document.getElementById('stop-motor').addEventListener('click', async () => {
        const slider = document.getElementById('slider-M');
        slider.value = 0;
        updateSliderDisplay(slider);
        await sendCommand('M', 0);
    });

    document.getElementById('btn-send-all').addEventListener('click', sendAllPending);
    document.getElementById('btn-home').addEventListener('click', goHome);
    document.getElementById('btn-save-pos').addEventListener('click', saveCurrentPosition);
    document.getElementById('btn-add-wait').addEventListener('click', addWaitStep);
    document.getElementById('btn-clear-wf').addEventListener('click', () => {
        currentWorkflowSequence = [];
        renderWorkflowSequence();
    });
    document.getElementById('btn-save-wf').addEventListener('click', saveWorkflow);
    document.getElementById('btn-run-wf').addEventListener('click', () => runWorkflow());
    document.getElementById('btn-save-automation').addEventListener('click', saveAutomation);
    document.getElementById('btn-reset-automation').addEventListener('click', resetAutomationForm);
    document.getElementById('automation-action').addEventListener('change', syncAutomationWorkflowVisibility);

    document.querySelectorAll('.btn-cal').forEach(button => {
        button.addEventListener('click', async () => {
            const id = button.dataset.joint;
            const slider = document.getElementById(`slider-${id}`);
            if (!slider) {
                return;
            }

            slider.value = 90;
            updateSliderDisplay(slider);
            await sendCommand(id, 90);
        });
    });

    window.addEventListener('keydown', event => {
        if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT') {
            return;
        }

        if (event.code === 'Space' || event.code === 'Enter') {
            event.preventDefault();
            sendAllPending();
        }

        if (event.code === 'KeyH') {
            goHome();
        }
    });
}

async function initialize() {
    wireControls();
    resetAutomationForm();
    renderWorkflowSequence();
    await Promise.all([loadPositions(), loadWorkflows(), loadAutomations()]);
    await pollSensorState();
    sensorPollHandle = window.setInterval(pollSensorState, 750);
}

window.goToPosition = goToPosition;
window.deletePosition = deletePosition;
window.executeWorkflowByName = executeWorkflowByName;
window.deleteWorkflow = deleteWorkflow;
window.removeStep = removeStep;
window.editAutomation = editAutomation;
window.deleteAutomation = deleteAutomation;
window.toggleAutomation = toggleAutomation;

window.addEventListener('load', initialize);
