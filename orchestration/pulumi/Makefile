current_dir := $(shell pwd)
cluster_name ?= ## Cluster name to manage.
cluster_project_name ?= wallaroo## Project name to assign as a tag to the cluster.
provider ?= azure## Provider to launch cluster in (azure).
location ?= eastus## Location to launch cluster in (eastus, eastus2, centralus, westus2).
availability_zone ?= 1## Availability Zone to launch cluster in (1,2,3).
cluster_pub ?= ~/.ssh/azure/wallaroo.pem.pub ## Public file to use for ssh keys to cluster.
cluster_pem ?= ~/.ssh/azure/wallaroo.pem ## PEM file to use for ssh keys for cluster.
use_proximity_placement_group ?= true## Whether to use proximity placement groups or not (true, false).

vm_sku ?= Standard_D3_v2## Type of VM to use for VM Scale Set
ansible_parallelism ?= default## Number of machines to process in parallel for Ansible
num_leaders ?= 1## Number of leader nodes (1 by default)
num_followers ?= 2## Number of follower nodes (2 by default)
ansible_system_cpus ?= ## Number of cpus to dedicate for system processes (the rest are isolated for user processes)
ansible_isolcpus ?= false## Use isolcpus kernel boot param
ansible_install_devtools ?= false## Install dev tools on nodes
ansible_raid_level ?= 0## raid level for ansible for local instance store ssds
ansible_raid_fs ?= ext4## raid filesystem for ansible for local instance store ssds
ptpd_offset_max ?= 0.00025## ptpd offset tolerance beyond which things care considered out of sync (default is 250 microseconds)

num_instances_arg=$(shell echo $$(( $(num_leaders) + $(num_followers) )))
resource_group_name="$(cluster_name)-$(location)_rg"
vnet_name="$(cluster_name)-$(location)_vnet"
subnet_name="$(cluster_name)-$(location)_snet"
ip_name="$(cluster_name)-$(location)_ip"
nic_name="$(cluster_name)-$(location)_nic"
nsg_name="$(cluster_name)-$(location)_nsg"
vmss_name="$(cluster_name)-$(location)_vmss"
vm_name="$(cluster_name)-$(location)_vm"
ppg_name="$(cluster_name)-$(location)_ppg"
app_name="$(cluster_name)-k8s-$(location)_app"
np_name="default"
sp_name="$(cluster_name)-k8s-$(location)_sp"
app_name="$(cluster_name)-k8s-$(location)_app"
k8s_dns_prefix="$(cluster_name)-k8s-$(location)"

k8s_network_policy ?= "calico"## Network Policy to use for k8s
kubernetes_version ?= "1.18.4"## Kubernetes version to use
cluster_os_image?="Canonical:UbuntuServer:18.04-LTS:latest" ## Image to use for cluster
custom_os_image ?= ## Custom OS Image to use for vm creation

ansible_playbook_path ?= ## Path to custom ansible playbook
extra_ansible_vars ?= ## Extra ansible vars to use with custom playbook

inventory_script := inventory.$(cluster_name)-$(location).yaml
ansible_user ?= ubuntu
ansible_password ?= ubuntu
all_instances := 'wallaroo-*'
follower_instances := 'wallaroo-followers'
ssh_path ?="/home/${ansible_user}/.ssh/authorized_keys"

sync_dir ?= ## Directory to sync to cluster
dest_dir ?= ## Directory to placed synced directory in cluster

# if debug shell command output requested
ifdef DEBUG_SHELL
 SHELL = /bin/sh -x
endif

ansible_version := $(shell ansible --version | grep ansible | awk '{print $$2}')
ansible_required := 2.1.1.0

# check ansible version
ifneq ($(ansible_required),$(ansible_version))
  $(error Ansible version '$(ansible_required)' required! Your ansible version is '$(ansible_version)'.)
endif

# Make sure we have a valid value for provider
ifdef provider
  ifeq (,$(filter $(provider),azure))
    $(error Unknown provider option "$(provider). \
      Valid option is 'azure'")
  endif
endif

# Make sure we have a valid value for ansible_isolcpus
ifdef ansible_isolcpus
  ifeq (,$(filter $(ansible_isolcpus),false true))
    $(error Unknown ansible_isolcpus option "$(ansible_isolcpus). \
      Valid options are 'true' and 'false'")
  endif
endif

# Make sure we have a valid value for ansible_install_devtools
ifdef ansible_install_devtools
  ifeq (,$(filter $(ansible_install_devtools),false true))
    $(error Unknown ansible_install_devtools option "$(ansible_install_devtools). \
      Valid options are 'true' and 'false'")
  endif
endif

# set arguments for ansible raid_level variable
ifeq ($(ansible_raid_level),)
  ansible_raid_level_arg :=
else
  ansible_raid_level_arg := raid_level=$(ansible_raid_level)
endif

# set arguments for ansible system_cpus variable
ifeq ($(ansible_raid_fs),)
  ansible_raid_fs_arg :=
else
  ansible_raid_fs_arg := raid_fs=$(ansible_raid_fs)
endif

# set arguments for ansible system_cpus variable
ifeq ($(ansible_system_cpus),)
  ansible_sys_cpus_arg :=
else
  ansible_sys_cpus_arg := system_cpus=$(ansible_system_cpus)
endif

# set arguments for ansible parallelism
ifeq ($(ansible_parallelism),default)
  ansible_parallelism_arg :=
else
  ansible_parallelism_arg := --forks=$(ansible_parallelism)
endif

ifdef use_proximity_placement_group
  ifeq (,$(filter $(use_proximity_placement_group),false true))
    $(error Unknown use_proximity_placement_group option "$(use_proximity_placement_group). Valid \
      options are 'true' and 'false'")
  endif
endif

ifeq ($(use_proximity_placement_group),true)
  ifneq ($(provider),azure)
    $(error Can't use use_proximity_placement_group=true unless using provider=azure.)
  endif
  ppg_arg := -var proximity_placement_group=wallaroo-$(cluster_name)
endif

cluster_full_pem := $(shell echo $(cluster_pem))
rsync_opts := \"--exclude=.git -aHxv --numeric-ids --delete --progress \
          -e 'ssh -T -x -o StrictHostKeyChecking=no -o Compression=no \
          -i $(cluster_full_pem)'
user_rsync_opts ?= # User provdied rsync options
rsync_opts := $(rsync_opts) $(user_rsync_opts)

.PHONY: all up init init-pulumi-vnet-stack init-pulumi-cluster-stack sleep60 cluster\
	configure create-vnet create-ppg create-vmss import-vmss destroy-vmss\
	destroy-ppg destroy-vnet destroy-vnet-state destroy-cluster-state

sleep60: # sleep 60 seconds
	@echo "\033[36m==> Sleeping 60 seconds for cluster '$(cluster_name)' in\
 location '$(location)' at provider '$(provider)' to spin up...\033[0m"
	@sleep 60

cluster: in_cluster=true
cluster: check-cluster-name init up sleep60 generate-inventory configure ## Creates a cluster and configures it with Ansible
cluster-k8s: check-cluster-name init-pulumi-k8s-stack create-k8s enable-k8s-dashboard enable-k8s-http-routing set-k8s-context ## Creates a kubernetes cluster, enables the dashboard and http application routing addons, retrieves credentials and sets context

vm: check-cluster-name init-vm create-vm sleep60 generate-vm-inventory configure ## Creates a VM and configures it with Ansible

init: check-cluster-name init-pulumi-vnet-stack init-pulumi-cluster-stack ## Initialize Pulumi stacks
init-vm: check-cluster-name init-pulumi-vm-stack ## Initialize Pulumi VM stack

up: check-cluster-name create-vnet create-ppg create-vmss import-vmss

destroy: check-cluster-name destroy-vmss destroy-ppg destroy-vnet destroy-cluster-state destroy-vnet-state delete-inventory-file ## Run cluster and vnet destroy steps

destroy-vm: check-cluster-name destroy-vm-cloud destroy-vm-state delete-inventory-file ## Run vm destroy steps

destroy-k8s: check-cluster-name destroy-k8s-cluster destroy-k8s-state ## Run Kubernetes destroy steps

check-ptpd-offsets: check-cluster-name ## Check ptpd offsets for all followers in the cluster
	@echo "\033[36m==> Running ansible ptpd check for followers in cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	@echo "\033[36m==> Using '$(ptpd_offset_max)' as maximum offset allowed.\033[0m"
	@echo "\033[36m==> NOTE: Use 'ptpd_offset_max=<offset>' to change.\033[0m"
	ansible $(follower_instances) \
          -i ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no \
          -i  $(cluster_full_pem)"  -u $(ansible_user) -m shell -a \
          'tail -n 1 /var/log/ptpd-stats.log | awk -F\, '"'"'{if (length($$6) > 0 && \
           ($$6 > $(ptpd_offset_max) || $$6 < -$(ptpd_offset_max))) {print $$6; exit 1}}'"'"
	@echo "\033[36m==> Successfully ran ansible ptpd check for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	@echo "\033[36m==> All followers are currently within offset tolerance of '$(ptpd_offset_max)'.\033[0m"

test-ansible-connection: check-cluster-name ## Check ansible connectivity/authentication with servers
	@echo "\033[36m==> Running ansible connectivity/authentication check for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	ansible $(all_instances) \
          -i ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no \
          -i  $(cluster_full_pem)"  -u $(ansible_user) -m raw -a "hostname -A"
	@echo "\033[36m==> Successfully ran ansible connectivity/authentication check for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"

sync-wallaroo: check-cluster-name ## Rsync wallaroo repo to nodes
	@echo "\033[36m==> Running ansible to rsync wallaroo repo to cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	ansible $(all_instances) \
          -i ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no \
          -i  $(cluster_full_pem)"  -u $(ansible_user) -m file -a "path=$(abspath $(dir $(MAKEFILE_LIST))/../../..) mode=0777 \
          state=directory" --become
	ansible $(all_instances) \
          -i ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no \
          -i  $(cluster_full_pem)"  -u $(ansible_user) -m synchronize -a "src=$(abspath \
          $(dir $(MAKEFILE_LIST))/../..) dest=$(abspath $(dir $(MAKEFILE_LIST))/../../..) \
          recursive=yes rsync_opts=\"--exclude=.git -e 'ssh  -o StrictHostKeyChecking=no \
          -i $(cluster_full_pem)'\""
	@echo "\033[36m==> Successfully ran ansible to rsync wallaroo repo to cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'!\033[0m"

sync-dir: check-cluster-name ## Rsync directory to nodes
	@echo "\033[36m==> Running ansible to rsync provided directory to cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	ansible $(all_instances) \
          -i ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no \
          -i  $(cluster_full_pem)"  -u $(ansible_user) -m file -a "path=$(abspath $(dir $(dest_dir))) mode=0777 \
          state=directory" --become
	ansible $(all_instances) \
          -i ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no \
          -i  $(cluster_full_pem)"  -u $(ansible_user) -m synchronize -a "src=$(abspath \
          $(dir $(sync_dir))) dest=$(abspath $(dir $(dest_dir))) \
          recursive=yes rsync_opts=$(rsync_opts)\""
	@echo "\033[36m==> Successfully ran ansible to rsync provided directory to cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'!\033[0m"


configure: check-cluster-name ## Configure nodes using ansible
	@echo "\033[36m==> Running ansible playbook for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	ansible-playbook $(ansible_parallelism_arg) \
          --timeout=30 -i \
          ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no -i \
          $(cluster_full_pem)" --extra-vars "cluster_name=$(cluster_name) \
          cluster_project_name=$(cluster_project_name) \
          provider=$(provider) \
          $(provider)_region=$(location) isolcpus=$(ansible_isolcpus) \
	  install_devtools=$(ansible_install_devtools) ssh_key_file=$(cluster_full_pem) \
          $(ansible_raid_level_arg) $(ansible_raid_fs_arg) \
          $(ansible_sys_cpus_arg)" -u $(ansible_user) \
          ../ansible/playbooks/$(provider).yml
	@echo "\033[36m==> Successfully ran ansible playbook for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'!\033[0m"

init-pulumi-vnet-stack: check-cluster-name ## Initialize pulumi vnet stack
		@echo "\033[36m==> Confirming Virtual Network Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-vnet && pulumi stack init '$(cluster_name)-$(location)'
	@echo "\033[36m==> Successfully confirmed Virtual Network Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'!\033[0m"

init-pulumi-cluster-stack: check-cluster-name ## Initialize pulumi cluster stack
	@echo "\033[36m==> Confirming Cluster Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-cluster && pulumi stack init '$(cluster_name)-$(location)'
	@echo "\033[36m==> Successfully confirmed Cluster Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'!\033[0m"


init-pulumi-vm-stack: check-cluster-name ## Initialize pulumi vnet stack
		@echo "\033[36m==> Confirming Virtual Machine Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-vm && pulumi stack init '$(cluster_name)-$(location)'
	@echo "\033[36m==> Successfully confirmed Virtual Machine Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'!\033[0m"

init-pulumi-k8s-stack: check-cluster-name ## Initialize pulumi k8s cluster stack
	@echo "\033[36m==> Confirming k8s Cluster Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-k8s && pulumi stack init '$(cluster_name)-$(location)'
	@echo "\033[36m==> Successfully confirmed k8s Cluster Pulumi Stack is created for location \
'$(location)' at provider '$(provider)'!\033[0m"

create-vnet: check-cluster-name ## Create vnet
		@echo "vnet name: '$(vnet_name)'"
	@echo "\033[36m==> Confirming Virtual Network is created in location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-vnet && pulumi up -s '$(cluster_name)-$(location)' \
	--config "$(provider)-vnet:location=$(location)" \
	--config "$(provider)-vnet:resourcegroup-name=$(resource_group_name)" \
	--config "$(provider)-vnet:vnet-name=$(vnet_name)" \
	--config "$(provider)-vnet:subnet-name=$(subnet_name)" \
	--config "$(provider)-vnet:nsg-name=$(nsg_name)" \
	--config "$(provider)-vnet:project-name=$(cluster_project_name)" \
	--yes --non-interactive
	@echo "\033[36m==> Successfully confirmed Virtual Network is created in location \
'$(location)' at provider '$(provider)'!\033[0m"

create-vm: check-cluster-name ## Create vm
	@echo "\033[36m==> Confirming Virtual Machine is created in location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-vm && pulumi up -s '$(cluster_name)-$(location)' \
	--config "$(provider)-vm:location=$(location)" \
	--config "$(provider)-vm:resourcegroup-name=$(resource_group_name)" \
	--config "$(provider)-vm:vm-name=$(vm_name)" \
	--config "$(provider)-vm:vnet-name=$(vnet_name)" \
	--config "$(provider)-vm:ip-name=$(ip_name)" \
	--config "$(provider)-vm:nic-name=$(nic_name)" \
	--config "$(provider)-vm:os-image=$(cluster_os_image)" \
	--config "$(provider)-vm:custom-os-image-id=$(custom_os_image)" \
	--config "$(provider)-vm:vm-sku=$(vm_sku)" \
	--config "$(provider)-vm:username=$(ansible_user)" \
	--config "$(provider)-vm:password=$(ansible_password)" \
	--config "$(provider)-vm:ssh-path=$(ssh_path)" \
	--config "$(provider)-vm:ssh-key-data=$(shell cat ${cluster_pub})" \
	--config "$(provider)-vm:project-name=$(cluster_project_name)" \
	--yes --non-interactive
	@echo "\033[36m==> Successfully confirmed Virtual Machine is created in location \
'$(location)' at provider '$(provider)'!\033[0m"

create-ppg: check-cluster-name ## Create PPG
	@echo "\033[36m==> Confirming Proximity Placement Group is created in location \
'$(location)' at provider '$(provider)'...\033[0m"
	az ppg create --name $(ppg_name) --resource-group $(resource_group_name) --type Standard
	@echo "\033[36m==> Successfully confirmed Proximity Placement Group is created in location \
'$(location)' at provider '$(provider)'!\033[0m"

create-vmss: check-cluster-name ## Create VMSS
	@echo "\033[36m==> Confirming VM Scale Set is created in location \
'$(location)' at provider '$(provider)'...\033[0m"
	az vmss create -n $(vmss_name) --ppg $(ppg_name) \
	--image $(cluster_os_image) --admin-username $(ansible_user) \
	--ssh-key-value $(cluster_pub) --vm-sku $(vm_sku) \
	--instance-count $(num_instances_arg) --zones $(availability_zone) --vnet-name $(vnet_name) --subnet $(subnet_name)  -l $(location) \
	--public-ip-per-vm --accelerated-networking $(accelerated_networking) --resource-group $(resource_group_name) \
	--nsg $(nsg_name) --tags "environment=Development project='$(cluster_project_name)'"
	@echo "\033[36m==> Successfully confirmed VM Scale Set is created in location \
'$(location)' at provider '$(provider)'!\033[0m"

create-k8s: check-cluster-name ## Create k8s cluster
	@echo "\033[36m==> Confirming k8s cluster is created in location \
'$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-k8s && pulumi up -s '$(cluster_name)-$(location)' \
	--config "$(provider)-k8s:location=$(location)" \
	--config "$(provider)-k8s:resourcegroup-name=$(resource_group_name)" \
	--config "$(provider)-k8s:aks-cluster-name=$(cluster_name)" \
	--config "$(provider)-k8s:app-name=$(app_name)" \
	--config "$(provider)-k8s:node-pool-name=$(np_name)" \
	--config "$(provider)-k8s:sp-name=$(sp_name)" \
	--config "$(provider)-k8s:kubernetes-version=$(kubernetes_version)" \
	--config "$(provider)-k8s:dns-prefix=$(k8s_dns_prefix)" \
	--config "$(provider)-k8s:network-policy=$(k8s_network_policy)" \
	--config "$(provider)-k8s:node-count=$(num_instances_arg)" \
	--config "$(provider)-k8s:vm-sku=$(vm_sku)" \
	--config "$(provider)-k8s:username=$(ansible_user)" \
	--config "$(provider)-k8s:ssh-key-data=$(shell cat ${cluster_pub})" \
	--config "$(provider)-k8s:project-name=$(cluster_project_name)" \
	--yes --non-interactive
	@echo "\033[36m==> Successfully confirmed k8s is created in location \
'$(location)' at provider '$(provider)'!\033[0m"

import-vmss: check-cluster-name ## Import exisiting VMSS into Pulumi stack
import-vmss: vmss_id=$(shell az vmss show -g $(resource_group_name) -n $(vmss_name) -o json | jq '.id')
import-vmss:
	@echo "\033[36m==> Confirming VM Scale Set is imported  to Pulumi\
stack '$(cluster_name)'...\033[0m"
	cd $(provider)-cluster && pulumi up -s '$(cluster_name)-$(location)' --yes --non-interactive  \
	--config "$(provider)-cluster:vmss-name=$(vmss_name)" \
	--config "$(provider)-cluster:vmss-id=$(vmss_id)" && \
	pulumi stack export -s '$(cluster_name)-$(location)' | jq 'del(.deployment.resources[].external)' \
	| pulumi stack import -s '$(cluster_name)-$(location)' --force --non-interactive
	@echo "\033[36m==> Successfully confirmed VM Scale Set is imported to Pulumi \
stack '$(cluster_name)'!\033[0m"

destroy-vmss: check-cluster-name ## Manually destroy VMSS cluster in location
	@echo "\033[36m==> Destroying VMSS cluster in location '$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-cluster && pulumi destroy -s '$(cluster_name)-$(location)' --yes
	@echo "\033[36m==> Successfully confirmed VMSS cluster is destroyed in location \
'$(location)' at provider '$(provider)'!\033[0m"

destroy-ppg: check-cluster-name ## Manually destroy PPG in location
	@echo "\033[36m==> Destroying PPG in location '$(location)' at provider '$(provider)'...\033[0m"
	az ppg delete --name $(ppg_name) --resource-group $(resource_group_name)
	@echo "\033[36m==> Successfully confirmed PPG is destroyed in location \
'$(location)' at provider '$(provider)'!\033[0m"

destroy-vnet: check-cluster-name ## Destroy VNet in location
	@echo "\033[36m==> Destroying VNet in location '$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-vnet && pulumi destroy -s '$(cluster_name)-$(location)' --yes
	@echo "\033[36m==> Successfully confirmed VNet is destroyed in location \
'$(location)' at provider '$(provider)'!\033[0m"

destroy-k8s-cluster: check-cluster-name ## Destroy k8s cluster in location
	@echo "\033[36m==> Destroying k8s Cluster in location '$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-k8s && pulumi destroy -s '$(cluster_name)-$(location)' --yes
	@echo "\033[36m==> Successfully confirmed k8s Cluster is destroyed in location \
'$(location)' at provider '$(provider)'!\033[0m"

destroy-vnet-state: check-cluster-name ## Destroy VNet Pulumi Stack state
	@echo "\033[36m==> Destroying VNet Pulumi Stack state...\033[0m"
	cd $(provider)-vnet && pulumi stack rm '$(cluster_name)-$(location)' --yes --non-interactive
	@echo "\033[36m==> VNet Pulumi Stack state successfully destroyed!\033[0m"

destroy-cluster-state: check-cluster-name ## Destroy Cluster Pulumi Stack state
	@echo "\033[36m==> Destroying Cluster Pulumi Stack state...\033[0m"
	cd $(provider)-cluster && pulumi stack rm '$(cluster_name)-$(location)' --yes --non-interactive
	@echo "\033[36m==> Cluster Pulumi Stack state successfully destroyed!\033[0m"

destroy-vm-cloud: check-cluster-name ## Destroy VM in location
	@echo "\033[36m==> Destroying Virtual Machine in location '$(location)' at provider '$(provider)'...\033[0m"
	cd $(provider)-vm && pulumi destroy -s '$(cluster_name)-$(location)' --yes
	@echo "\033[36m==> Successfully confirmed Virtual Machine is destroyed in location \
'$(location)' at provider '$(provider)'!\033[0m"

destroy-vm-state: check-cluster-name ## Destroy Cluster Pulumi Stack state
	@echo "\033[36m==> Destroying Virtual Machine Pulumi Stack state...\033[0m"
	cd $(provider)-vm && pulumi stack rm '$(cluster_name)-$(location)' --yes --non-interactive
	@echo "\033[36m==> Virtual Machine Pulumi Stack state successfully destroyed!\033[0m"

destroy-k8s-state: check-cluster-name ## Destroy k8s Cluster Pulumi Stack state
	@echo "\033[36m==> Destroying k8s Cluster Pulumi Stack state...\033[0m"
	cd $(provider)-k8s && pulumi stack rm '$(cluster_name)-$(location)' --yes --non-interactive
	@echo "\033[36m==> k8s Cluster Pulumi Stack state successfully destroyed!\033[0m"

enable-k8s-dashboard: check-cluster-name ## Enable Kubernetes dashboard addon
	@echo "\033[36m==> Enabling Kubernetes Dashboard addon in location \
'$(location)' at provider '$(provider)'...\033[0m"
	az aks enable-addons --name $(cluster_name) --resource-group $(resource_group_name) \
	--addons kube-dashboard
	@echo "\033[36m==> Successfully enabled Kubernetes Dashboard addon in location \
'$(location)' at provider '$(provider)' for cluster '$(cluster_name)'!\033[0m"

enable-k8s-http-routing: check-cluster-name ## Enable Kubernetes http application routing addon
	@echo "\033[36m==> Enabling Kubernetes http application routing addon in location \
'$(location)' at provider '$(provider)'...\033[0m"
	az aks enable-addons --name $(cluster_name) --resource-group $(resource_group_name) \
	--addons http_application_routing
	@echo "\033[36m==> Successfully enabled Kubernetes http application routing addon in location \
'$(location)' at provider '$(provider)' for cluster '$(cluster_name)'!\033[0m"

display-k8s-http-routing-zone-name: check-cluster-name ## Displays Kubernetes http application routing zone name
	@echo "\033[36m==> Retrieving Kubernetes http application routing zone name in location \
'$(location)' at provider '$(provider)' for cluster '$(cluster_name)'...\033[0m"
	az aks show --name $(cluster_name) --resource-group $(resource_group_name) \
	--query addonProfiles.httpApplicationRouting.config.HTTPApplicationRoutingZoneName -o table
	@echo "\033[36m==> Successfully retrieved Kubernetes http application routing zone name in location \
'$(location)' at provider '$(provider)' for cluster '$(cluster_name)'!\033[0m"


set-k8s-context: check-cluster-name ## Displays Kubernetes http application routing zone name
	@echo "\033[36m==> Retrieves Kubernetes credentials and setting context in location \
'$(location)' at provider '$(provider)' for cluster '$(cluster_name)'...\033[0m"
	az aks get-credentials --name $(cluster_name) --resource-group $(resource_group_name) \
	--overwrite-existing
	@echo "\033[36m==> Successfully retrieved Kubernetes credentials and set context in location \
'$(location)' at provider '$(provider)' for cluster '$(cluster_name)'!\033[0m"

check-cluster-name: ## Check for valid cluster name
	$(if $(cluster_name),,$(error 'cluster_name' cannot be empty!))
	$(if $(filter $(cluster_name),$(shell echo '$(cluster_name)' | sed 's/[^-a-zA-Z0-9]//g')),,$(error 'cluster_name' can only have [-a-zA-Z0-9] in it!))

generate-inventory: ## Generates inventory file
	./generate_inventory.sh $(vmss_name) $(resource_group_name) $(num_leaders) $(num_followers) > ../ansible/inventory.$(cluster_name)-$(location).yaml

generate-vm-inventory: ## Generates VM inventory file
	./generate_vm_inventory.sh $(vm_name) $(resource_group_name) > ../ansible/inventory.$(cluster_name)-$(location).yaml

delete-inventory-file: ## Deletes inventory file
	rm ../ansible/inventory.$(cluster_name)-$(location).yaml

ansible-custom-playbook: check-cluster-name ## Run custom playbook on nodes
	@echo "\033[36m==> Running ansible playbook for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'...\033[0m"
	ansible-playbook $(ansible_parallelism_arg) \
          --timeout=30 -i \
          ../ansible/$(inventory_script) --ssh-common-args="-o StrictHostKeyChecking=no -i \
          $(cluster_full_pem)" --extra-vars "$(extra_ansible_vars)" -u $(ansible_user) \
          $(ansible_playbook_path)
	@echo "\033[36m==> Successfully ran ansible playbook for cluster \
'$(cluster_name)' in location '$(location)' at provider '$(provider)'!\033[0m"


help: ## Self-documenting help command
	@echo 'Usage: make [option1=value] [option2=value,...] [target]'
	@echo ''
	@echo 'Options:'
	@grep -E '^[a-zA-Z_-]+ *\?=.*?## .*$$' $(MAKEFILE_LIST) |  sed s/?=/,,/ | awk \
          'BEGIN {FS = ",,"}; {printf "\033[36m%-30s\033[0m ##%s\n", $$1, $$2}'\
          | awk 'BEGIN {FS = "## "}; {printf \
          "%s %s \033[36m(Default: %s)\033[0m\n", $$1, $$3, $$2}'
	@echo ''
	@echo 'Targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk \
          'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", \
          $$1, $$2}'

# rule to print info about make variables, works only with make 3.81 and above
# to use invoke make with a target of print-VARNAME, e.g.,
# make print-CCFLAGS
print-%:
	@echo '$*=$($*)'
	@echo '  origin = $(origin $*)'
	@echo '  flavor = $(flavor $*)'
	@echo '   value = $(value  $*)'

