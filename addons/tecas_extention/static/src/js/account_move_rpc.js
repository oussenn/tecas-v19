/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { BooleanToggleField, booleanToggleField } from "@web/views/fields/boolean_toggle/boolean_toggle_field";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

class CustomBooleanToggleConfirm extends BooleanToggleField {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.orm = useService("orm");
        this.actionService = useService("action");
    }

    async onChange(newValue) {
        if (newValue === true) {
            const record = this.props.record;
            const recordId = record.data.id;
            const partner = record.data.partner_id;
            const partnerId = partner?.id || (Array.isArray(partner) ? partner[0] : partner);

            try {
                const [invoiceData, partnerData] = await Promise.all([
                    this.orm.read("account.move", [recordId], ["amount_total"]),
                    this.orm.read("res.partner", [partnerId], ["is_company"]),
                ]);

                const amountTotal = invoiceData[0]?.amount_total || 0;
                const isCompany = partnerData[0]?.is_company || false;
                const limit = isCompany ? 5000 : 20000;

                console.log("amountTotal:", amountTotal, "limit:", limit);

                if (amountTotal > limit) {
                    this.dialogService.add(ConfirmationDialog, {
                        body: `Le montant total dépasse ${limit}. Voulez-vous scinder cette facture ?`,
                        confirm: async () => {
                            this.state.value = true;
                            await record.update({ cash: true }, { save: false });
                            const action = await this.orm.call("account.move", "action_open_split_wizard", [[recordId]]);
                            if (action) {
                                await this.actionService.doAction(action);
                            }
                        },
                        cancel: async () => {
                            this.state.value = false;
                        },
                    });
                } else {
                    this.state.value = true;
                    await record.update({ cash: true }, { save: false });
                }
            } catch (error) {
                console.error("Error:", error);
                this.state.value = newValue;
                await record.update({ cash: newValue }, { save: false });
            }
        } else {
            this.state.value = newValue;
            await this.props.record.update({ cash: newValue }, { save: false });
        }
    }
}

registry.category("fields").add("custom_boolean_toggle_confirm", {
    ...booleanToggleField,
    component: CustomBooleanToggleConfirm,
    extractProps({ options }, dynamicInfo) {
        return {
            autosave: false,
            readonly: dynamicInfo.readonly,
        };
    },
});
