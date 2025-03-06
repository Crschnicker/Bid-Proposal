// Adjustment Tracking Module

// Global array to store adjustment history
let adjustmentHistory = [];

// Adjustment tracking class
class AdjustmentTracker {
    constructor() {
        // Load existing history from localStorage
        this.loadHistory();
    }

    // Load adjustment history from localStorage
    loadHistory() {
        const storedHistory = localStorage.getItem('bidAdjustmentHistory');
        adjustmentHistory = storedHistory ? JSON.parse(storedHistory) : [];
    }

    // Save adjustment history to localStorage
    saveHistory() {
        localStorage.setItem('bidAdjustmentHistory', JSON.stringify(adjustmentHistory));
    }

    // Record an adjustment
    recordAdjustment(details) {
        const adjustmentRecord = {
            id: Date.now(), // Unique identifier
            timestamp: new Date().toISOString(),
            user: this.getCurrentUser(), // Implement method to get current user
            ...details
        };

        adjustmentHistory.push(adjustmentRecord);
        this.saveHistory();
        this.updateAdjustmentHistoryDisplay();
        return adjustmentRecord;
    }

    // Get current user (you'll need to implement this based on your authentication system)
    getCurrentUser() {
        // This is a placeholder. Replace with actual user retrieval logic
        return {
            username: document.getElementById('currentUsername')?.textContent || 'Unknown User',
            id: document.getElementById('currentUserId')?.textContent || null
        };
    }

    // Undo a specific adjustment
    undoAdjustment(adjustmentId) {
        const adjustmentIndex = adjustmentHistory.findIndex(adj => adj.id === adjustmentId);
        if (adjustmentIndex === -1) {
            console.error('Adjustment not found');
            return false;
        }

        const adjustment = adjustmentHistory[adjustmentIndex];

        try {
            // Revert the specific adjustment
            this.revertAdjustment(adjustment);

            // Remove the adjustment from history
            adjustmentHistory.splice(adjustmentIndex, 1);
            this.saveHistory();
            this.updateAdjustmentHistoryDisplay();

            return true;
        } catch (error) {
            console.error('Error undoing adjustment:', error);
            return false;
        }
    }

    // Revert a specific adjustment
    revertAdjustment(adjustment) {
        const { section, type, direction, percentage, originalValues } = adjustment;

        // Get the wrapper for the specific section
        const wrapper = $(`#${section.toLowerCase()}Wrapper`);

        // Determine the multiplier (opposite of original adjustment)
        const reverseMultiplier = direction === 'increase' ? (1 - percentage / 100) : (1 + percentage / 100);

        if (type === 'Materials') {
            // Revert material costs
            wrapper.find('.itemsTable tbody tr').each(function(index) {
                const costInput = $(this).find('.costInput');
                const originalCost = originalValues[index].cost;
                costInput.val(originalCost.toFixed(2));

                // Revert factor code item costs if applicable
                const factorCode = $(this).find('.factorCodeInput').val();
                if (factorCode && window.factorCodeItemsCache && window.factorCodeItemsCache[factorCode]) {
                    window.factorCodeItemsCache[factorCode].forEach((item, itemIndex) => {
                        item.cost = originalValues[index].factorCodeItems[itemIndex].cost;
                    });
                }
            });
        } else {
            // Revert labor hours
            wrapper.find('.itemsTable tbody tr').each(function(index) {
                const laborInput = $(this).find('.laborHoursInput');
                const originalLaborHours = originalValues[index].laborHours;
                laborInput.val(originalLaborHours.toFixed(4));
            });
        }

        // Update line costs and totals
        wrapper.find('.itemsTable tbody tr').each(function() {
            updateLineAndTotalCosts($(this).find('.quantity input')[0]);
        });

        // Update all totals and budgets
        updateTotalCost(wrapper);
        updateBudgetTotals();
    }

    // Update the adjustment history display
    updateAdjustmentHistoryDisplay() {
        const historyTable = document.getElementById('adjustmentHistoryTable');
        if (!historyTable) return;

        // Clear existing rows
        while (historyTable.rows.length > 1) {
            historyTable.deleteRow(1);
        }

        // Populate with current history
        adjustmentHistory.forEach(adjustment => {
            const row = historyTable.insertRow();
            row.innerHTML = `
                <td>${new Date(adjustment.timestamp).toLocaleString()}</td>
                <td>${adjustment.user.username}</td>
                <td>${adjustment.section}</td>
                <td>${adjustment.type}</td>
                <td>${adjustment.direction}</td>
                <td>${adjustment.percentage}%</td>
                <td>
                    <button onclick="adjustmentTracker.undoAdjustment(${adjustment.id})" 
                            class="btn btn-sm btn-warning">Undo</button>
                </td>
            `;
        });
    }
}

// Instantiate the adjustment tracker
const adjustmentTracker = new AdjustmentTracker();

// Modify the existing applyAdjustments function to use the tracker
function applyAdjustments() {
    if (!checkInputsValid()) return;

    const selectedType = document.querySelector('input[name="adjustmentType"]:checked').value;
    const selectedSection = document.querySelector('input[name="category"]:checked').value;
    const selectedDirection = document.querySelector('input[name="direction"]:checked').value;
    const percentage = parseFloat(percentageInput.value);
    const multiplier = selectedDirection === 'increase' ? (1 + percentage / 100) : (1 - percentage / 100);
    
    const wrapper = $(`#${selectedSection.toLowerCase()}Wrapper`);

    // Store original values for potential undo
    const originalValues = [];

    if (selectedType === 'Materials') {
        // First, track original values
        wrapper.find('.itemsTable tbody tr').each(function() {
            const costInput = $(this).find('.costInput');
            const currentCost = parseFloat(costInput.val()) || 0;
            const factorCode = $(this).find('.factorCodeInput').val();
            
            const originalItem = {
                cost: currentCost,
                factorCodeItems: []
            };

            // Store original factor code item costs
            if (factorCode && window.factorCodeItemsCache && window.factorCodeItemsCache[factorCode]) {
                originalItem.factorCodeItems = window.factorCodeItemsCache[factorCode].map(item => ({
                    cost: item.cost
                }));
            }

            originalValues.push(originalItem);

            // Adjust costs
            costInput.val((currentCost * multiplier).toFixed(2));

            // Adjust factor code item costs
            if (factorCode && window.factorCodeItemsCache && window.factorCodeItemsCache[factorCode]) {
                window.factorCodeItemsCache[factorCode].forEach(item => {
                    item.cost = (parseFloat(item.cost) * multiplier);
                });
            }
        });

        // Rest of the materials adjustment logic remains the same
        // (other materials calculation, updating displays, etc.)
    } else {
        // Labor adjustments
        wrapper.find('.itemsTable tbody tr').each(function() {
            const laborInput = $(this).find('.laborHoursInput');
            const currentLabor = parseFloat(laborInput.val()) || 0;
            
            // Store original labor hours
            originalValues.push({
                laborHours: currentLabor
            });

            // Adjust labor hours
            laborInput.val((currentLabor * multiplier).toFixed(4));
        });
    }

    // Update line costs for all rows
    wrapper.find('.itemsTable tbody tr').each(function() {
        updateLineAndTotalCosts($(this).find('.quantity input')[0]);
    });

    // Update all totals and budgets
    updateTotalCost(wrapper);
    updateBudgetTotals();

    // Record the adjustment
    adjustmentTracker.recordAdjustment({
        section: selectedSection,
        type: selectedType,
        direction: selectedDirection,
        percentage: percentage,
        originalValues: originalValues
    });
    
    // Clear the form
    clearForm();
}

// Modify the existing HTML to include adjustment history table
function addAdjustmentHistoryTable() {
    const adjustmentTab = document.getElementById('Adjustment');
    if (!adjustmentTab) return;

    const historyTableHTML = `
        <div class="adjustment-history-container">
            <h4>Adjustment History</h4>
            <table id="adjustmentHistoryTable" class="table table-striped">
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>User</th>
                        <th>Section</th>
                        <th>Type</th>
                        <th>Direction</th>
                        <th>Percentage</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Adjustment history rows will be dynamically added here -->
                </tbody>
            </table>
        </div>
    `;

    // Append the history table to the Adjustment tab
    adjustmentTab.insertAdjacentHTML('beforeend', historyTableHTML);

    // Initialize the history display
    adjustmentTracker.updateAdjustmentHistoryDisplay();
}

// Call this when the document is ready
document.addEventListener('DOMContentLoaded', function() {
    // Add the adjustment history table to the Adjustment tab
    addAdjustmentHistoryTable();
});