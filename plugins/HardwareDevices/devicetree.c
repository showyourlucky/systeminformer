/*
 * Copyright (c) 2022 Winsider Seminars & Solutions, Inc.  All rights reserved.
 *
 * This file is part of System Informer.
 *
 * Authors:
 *
 *     jxy-s   2022-2023
 *
 */

#include "devices.h"
#include <toolstatusintf.h>

#include <devguid.h>

typedef struct _DEVICE_NODE
{
    PH_TREENEW_NODE Node;
    PH_SH_STATE ShState;
    PPH_DEVICE_ITEM DeviceItem;
    PPH_LIST Children;
    ULONG_PTR IconIndex;
    PH_STRINGREF TextCache[PhMaxDeviceProperty];
} DEVICE_NODE, *PDEVICE_NODE;

typedef struct _DEVICE_TREE
{
    PPH_DEVICE_TREE Tree;
    PPH_LIST Nodes;
    PPH_LIST Roots;
} DEVICE_TREE, *PDEVICE_TREE;

static BOOLEAN AutoRefreshDeviceTree = TRUE;
static BOOLEAN ShowDisconnected = TRUE;
static BOOLEAN ShowSoftwareComponents = TRUE;
static BOOLEAN HighlightUpperFiltered = TRUE;
static BOOLEAN HighlightLowerFiltered = TRUE;
static BOOLEAN ShowDeviceInterfaces = TRUE;
static BOOLEAN ShowDisabledDeviceInterfaces = TRUE;
static ULONG DeviceProblemColor = 0;
static ULONG DeviceDisabledColor = 0;
static ULONG DeviceDisconnectedColor = 0;
static ULONG DeviceHighlightColor = 0;
static ULONG DeviceInterfaceColor = 0;
static ULONG DeviceDisabledInterfaceColor = 0;
static ULONG DeviceArrivedColor = 0;
static ULONG DeviceHighlightingDuration = 0;

static PPH_OBJECT_TYPE DeviceTreeType = NULL;
static BOOLEAN DeviceTabCreated = FALSE;
static HWND DeviceTreeHandle = NULL;
static ULONG DeviceTreeVisibleColumns[PhMaxDeviceProperty] = { 0 };
static PH_CALLBACK_REGISTRATION DeviceNotifyRegistration = { 0 };
static PH_CALLBACK_REGISTRATION ProcessesUpdatedCallbackRegistration = { 0 };
static PH_CALLBACK_REGISTRATION SettingsUpdatedCallbackRegistration = { 0 };
static PDEVICE_TREE DeviceTree = NULL;
static HIMAGELIST DeviceImageList = NULL;
static PH_INTEGER_PAIR DeviceIconSize = { 16, 16 };
static PH_LIST DeviceFilterList = { 0 };
static PPH_MAIN_TAB_PAGE DevicesAddedTabPage = NULL;
static PTOOLSTATUS_INTERFACE ToolStatusInterface = NULL;
static BOOLEAN DeviceTabSelected = FALSE;
static ULONG DeviceTreeSortColumn = 0;
static PH_SORT_ORDER DeviceTreeSortOrder = NoSortOrder;
static PH_TN_FILTER_SUPPORT DeviceTreeFilterSupport = { 0 };
static PPH_TN_FILTER_ENTRY DeviceTreeFilterEntry = NULL;
static PH_CALLBACK_REGISTRATION SearchChangedRegistration = { 0 };
static PPH_POINTER_LIST DeviceNodeStateList = NULL;

static int __cdecl DeviceListSortByNameFunction(
    const void* Left,
    const void* Right
    )
{
    PDEVICE_NODE lhsNode;
    PDEVICE_NODE rhsNode;
    PPH_DEVICE_PROPERTY lhs;
    PPH_DEVICE_PROPERTY rhs;

    lhsNode = *(PDEVICE_NODE*)Left;
    rhsNode = *(PDEVICE_NODE*)Right;
    lhs = PhGetDeviceProperty(lhsNode->DeviceItem, PhDevicePropertyName);
    rhs = PhGetDeviceProperty(rhsNode->DeviceItem, PhDevicePropertyName);

    return PhCompareStringWithNull(lhs->AsString, rhs->AsString, TRUE);
}

static int __cdecl DeviceNodeSortFunction(
    const void* Left,
    const void* Right
    )
{
    PDEVICE_NODE lhsItem;
    PDEVICE_NODE rhsItem;

    lhsItem = *(PDEVICE_NODE*)Left;
    rhsItem = *(PDEVICE_NODE*)Right;

    return uintcmp(lhsItem->DeviceItem->InstanceIdHash, rhsItem->DeviceItem->InstanceIdHash);
}

static int __cdecl DeviceNodeSearchFunction(
    const void* Hash,
    const void* Item
    )
{
    PDEVICE_NODE item;

    item = *(PDEVICE_NODE*)Item;

    return uintcmp(PtrToUlong(Hash), item->DeviceItem->InstanceIdHash);
}

_Success_(return != NULL)
_Must_inspect_result_
PDEVICE_NODE DeviceTreeLookupNode(
    _In_ PDEVICE_TREE Tree,
    _In_ ULONG InstanceIdHash
    )
{
    PDEVICE_NODE* deviceItem;

    deviceItem = bsearch(
        UlongToPtr(InstanceIdHash),
        Tree->Nodes->Items,
        Tree->Nodes->Count,
        sizeof(PVOID),
        DeviceNodeSearchFunction
        );

    return deviceItem ? *deviceItem : NULL;
}

BOOLEAN DeviceTreeShouldIncludeDeviceItem(
    _In_ PPH_DEVICE_ITEM DeviceItem
    )
{
    if (DeviceItem->DeviceInterface)
    {
        if (!ShowDeviceInterfaces)
            return FALSE;

        if (ShowDisabledDeviceInterfaces)
            return TRUE;

        return PhGetDeviceProperty(DeviceItem, PhDevicePropertyInterfaceEnabled)->Boolean;
    }
    else
    {
        if (ShowDisconnected)
            return TRUE;

        if (!ShowSoftwareComponents && IsEqualGUID(&DeviceItem->ClassGuid, &GUID_DEVCLASS_SOFTWARECOMPONENT))
            return FALSE;

        return PhGetDeviceProperty(DeviceItem, PhDevicePropertyIsPresent)->Boolean;
    }
}

BOOLEAN DeviceTreeIsJustArrivedDeviceItem(
    _In_ PPH_DEVICE_ITEM DeviceItem
    )
{
    LARGE_INTEGER lastArrival;
    LARGE_INTEGER systemTime;
    LARGE_INTEGER elapsed;

    lastArrival = PhGetDeviceProperty(DeviceItem, PhDevicePropertyLastArrivalDate)->TimeStamp;

    if (lastArrival.QuadPart <= 0)
        return FALSE;

    PhQuerySystemTime(&systemTime);

    elapsed.QuadPart = systemTime.QuadPart - lastArrival.QuadPart;

    // convert to milliseconds
    elapsed.QuadPart /= 10000;

    // consider devices that arrived in that last 10 seconds as "just arrived"
    if (elapsed.QuadPart < (10 * 1000))
    {
        return TRUE;
    }

    return FALSE;
}

PDEVICE_NODE DeviceTreeCreateNode(
    _In_ PPH_DEVICE_ITEM Item,
    _Inout_ PPH_LIST Nodes
    )
{
    PDEVICE_NODE node;
    HICON iconHandle;

    node = PhAllocateZero(sizeof(DEVICE_NODE));

    PhInitializeTreeNewNode(&node->Node);
    node->Node.TextCache = node->TextCache;
    node->Node.TextCacheSize = RTL_NUMBER_OF(node->TextCache);

    node->DeviceItem = Item;
    iconHandle = PhGetDeviceIcon(Item, &DeviceIconSize);
    if (iconHandle)
    {
        node->IconIndex = PhImageListAddIcon(DeviceImageList, iconHandle);
        DestroyIcon(iconHandle);
    }
    else
    {
        node->IconIndex = 0; // Must be set to zero (dmex)
    }

    if (DeviceTreeFilterSupport.NodeList)
        node->Node.Visible = PhApplyTreeNewFiltersToNode(&DeviceTreeFilterSupport, &node->Node);
    else
        node->Node.Visible = TRUE;

    node->Children = PhCreateList(Item->ChildrenCount);
    for (PPH_DEVICE_ITEM item = Item->Child; item; item = item->Sibling)
    {
        if (DeviceTreeShouldIncludeDeviceItem(item))
            PhAddItemList(node->Children, DeviceTreeCreateNode(item, Nodes));
    }

    if (PhGetIntegerSetting(SETTING_NAME_DEVICE_SORT_CHILDREN_BY_NAME))
        qsort(node->Children->Items, node->Children->Count, sizeof(PVOID), DeviceListSortByNameFunction);

    PhAddItemList(Nodes, node);
    return node;
}

PDEVICE_TREE DeviceTreeCreate(
    _In_ PPH_DEVICE_TREE Tree
    )
{
    PDEVICE_TREE tree = PhCreateObject(sizeof(DEVICE_TREE), DeviceTreeType);

    tree->Nodes = PhCreateList(Tree->DeviceList->AllocatedCount);
    if (PhGetIntegerSetting(SETTING_NAME_DEVICE_SHOW_ROOT))
    {
        tree->Roots = PhCreateList(1);
        PhAddItemList(tree->Roots, DeviceTreeCreateNode(Tree->Root, tree->Nodes));
    }
    else
    {
        tree->Roots = PhCreateList(Tree->Root->ChildrenCount);
        for (PPH_DEVICE_ITEM item = Tree->Root->Child; item; item = item->Sibling)
        {
            if (DeviceTreeShouldIncludeDeviceItem(item))
                PhAddItemList(tree->Roots, DeviceTreeCreateNode(item, tree->Nodes));
        }

        if (PhGetIntegerSetting(SETTING_NAME_DEVICE_SORT_CHILDREN_BY_NAME))
            qsort(tree->Roots->Items, tree->Roots->Count, sizeof(PVOID), DeviceListSortByNameFunction);
    }

    qsort(tree->Nodes->Items, tree->Nodes->Count, sizeof(PVOID), DeviceNodeSortFunction);

    tree->Tree = PhReferenceObject(Tree);
    return tree;
}

VOID DeviceTreeDeleteProcedure(
    _In_ PVOID Object,
    _In_ ULONG Flags
    )
{
    PDEVICE_TREE tree = Object;

    for (ULONG i = 0; i < tree->Nodes->Count; i++)
    {
        PDEVICE_NODE node = tree->Nodes->Items[i];
        PhDereferenceObject(node->Children);
        PhFree(node);
    }

    PhDereferenceObject(tree->Nodes);
    PhDereferenceObject(tree->Roots);
    PhDereferenceObject(tree->Tree);
}

_Must_inspect_impl_
_Success_(return != NULL)
PDEVICE_TREE DeviceTreeCreateIfNecessary(
    _In_ BOOLEAN Force
    )
{
    PDEVICE_TREE deviceTree;
    PPH_DEVICE_TREE tree;

    tree = PhReferenceDeviceTreeEx(Force);
    if (Force || !DeviceTree || DeviceTree->Tree != tree)
    {
        deviceTree = DeviceTreeCreate(tree);
    }
    else
    {
        // the device tree hasn't changed, no need to create a new one
        deviceTree = NULL;
    }

    PhDereferenceObject(tree);

    return deviceTree;
}

VOID NTAPI DeviceTreePublish(
    _In_opt_ PDEVICE_TREE Tree
)
{
    PDEVICE_TREE oldTree;

    if (!Tree)
        return;

    TreeNew_SetRedraw(DeviceTreeHandle, FALSE);

    oldTree = DeviceTree;
    DeviceTree = Tree;
    DeviceFilterList.AllocatedCount = DeviceTree->Nodes->AllocatedCount;
    DeviceFilterList.Count = DeviceTree->Nodes->Count;
    DeviceFilterList.Items = DeviceTree->Nodes->Items;

    if (oldTree)
    {
        // TODO PhClearPointerList
        PhMoveReference(&DeviceNodeStateList, NULL);

        for (ULONG i = 0; i < DeviceTree->Nodes->Count; i++)
        {
            PDEVICE_NODE node = DeviceTree->Nodes->Items[i];
            PDEVICE_NODE old = DeviceTreeLookupNode(oldTree, node->DeviceItem->InstanceIdHash);

            if (old)
            {
                node->Node.Selected = old->Node.Selected;
            }

            if (DeviceTreeIsJustArrivedDeviceItem(node->DeviceItem))
            {
                PhChangeShStateTn(
                    &node->Node,
                    &node->ShState,
                    &DeviceNodeStateList,
                    NewItemState,
                    DeviceArrivedColor,
                    NULL
                    );
            }
        }
    }

    TreeNew_SetRedraw(DeviceTreeHandle, TRUE);

    TreeNew_NodesStructured(DeviceTreeHandle);

    if (DeviceTreeFilterSupport.FilterList)
        PhApplyTreeNewFilters(&DeviceTreeFilterSupport);

    PhClearReference(&oldTree);
}

NTSTATUS NTAPI DeviceTreePublishThread(
    _In_ PVOID Parameter
    )
{
    BOOLEAN force = PtrToUlong(Parameter) ? TRUE : FALSE;

    ProcessHacker_Invoke(DeviceTreePublish, DeviceTreeCreateIfNecessary(force));

    return STATUS_SUCCESS;
}

VOID DeviceTreePublishAsync(
    _In_ BOOLEAN Force
    )
{
    PhCreateThread2(DeviceTreePublishThread, ULongToPtr(Force ? 1ul : 0ul));
}

VOID InvalidateDeviceNodes(
    VOID
    )
{
    if (!DeviceTree)
        return;

    for (ULONG i = 0; i < DeviceTree->Nodes->Count; i++)
    {
        PDEVICE_NODE node;

        node = DeviceTree->Nodes->Items[i];

        PhInvalidateTreeNewNode(&node->Node, TN_CACHE_COLOR);
        TreeNew_InvalidateNode(DeviceTreeHandle, &node->Node);
    }
}

_Function_class_(PH_TN_FILTER_FUNCTION)
BOOLEAN NTAPI DeviceTreeFilterCallback(
    _In_ PPH_TREENEW_NODE Node,
    _In_opt_ PVOID Context
    )
{
    PDEVICE_NODE node = (PDEVICE_NODE)Node;

    if (!ToolStatusInterface->GetSearchMatchHandle())
        return TRUE;

    for (ULONG i = 0; i < ARRAYSIZE(node->DeviceItem->Properties); i++)
    {
        PPH_DEVICE_PROPERTY prop;

        if (!DeviceTreeVisibleColumns[i])
            continue;

        prop = PhGetDeviceProperty(node->DeviceItem, i);

        if (PhIsNullOrEmptyString(prop->AsString))
            continue;

        if (ToolStatusInterface->WordMatch(&prop->AsString->sr))
            return TRUE;
    }

    return FALSE;
}

VOID NTAPI DeviceTreeSearchChangedHandler(
    _In_opt_ PVOID Parameter,
    _In_opt_ PVOID Context
    )
{
    if (DeviceTabSelected)
        PhApplyTreeNewFilters(&DeviceTreeFilterSupport);
}

static int __cdecl DeviceTreeSortFunction(
    const void* Left,
    const void* Right
    )
{
    int sortResult;
    PDEVICE_NODE lhsNode;
    PDEVICE_NODE rhsNode;
    PPH_DEVICE_PROPERTY lhs;
    PPH_DEVICE_PROPERTY rhs;
    PH_STRINGREF srl;
    PH_STRINGREF srr;

    sortResult = 0;
    lhsNode = *(PDEVICE_NODE*)Left;
    rhsNode = *(PDEVICE_NODE*)Right;
    lhs = PhGetDeviceProperty(lhsNode->DeviceItem, DeviceTreeSortColumn);
    rhs = PhGetDeviceProperty(rhsNode->DeviceItem, DeviceTreeSortColumn);

    assert(lhs->Type == rhs->Type);

    if (!lhs->Valid && !rhs->Valid)
    {
        sortResult = 0;
    }
    else if (lhs->Valid && !rhs->Valid)
    {
        sortResult = 1;
    }
    else if (!lhs->Valid && rhs->Valid)
    {
        sortResult = -1;
    }
    else
    {
        switch (lhs->Type)
        {
        case PhDevicePropertyTypeString:
            sortResult = PhCompareString(lhs->String, rhs->String, TRUE);
            break;
        case PhDevicePropertyTypeUInt64:
            sortResult = uint64cmp(lhs->UInt64, rhs->UInt64);
            break;
        case PhDevicePropertyTypeInt64:
            sortResult = int64cmp(lhs->Int64, rhs->Int64);
            break;
        case PhDevicePropertyTypeUInt32:
            sortResult = uint64cmp(lhs->UInt32, rhs->UInt32);
            break;
        case PhDevicePropertyTypeInt32:
        case PhDevicePropertyTypeNTSTATUS:
            sortResult = int64cmp(lhs->Int32, rhs->Int32);
            break;
        case PhDevicePropertyTypeGUID:
            sortResult = memcmp(&lhs->Guid, &rhs->Guid, sizeof(GUID));
            break;
        case PhDevicePropertyTypeBoolean:
            {
                if (lhs->Boolean && !rhs->Boolean)
                    sortResult = 1;
                else if (!lhs->Boolean && rhs->Boolean)
                    sortResult = -1;
                else
                    sortResult = 0;
            }
            break;
        case PhDevicePropertyTypeTimeStamp:
            sortResult = int64cmp(lhs->TimeStamp.QuadPart, rhs->TimeStamp.QuadPart);
            break;
        case PhDevicePropertyTypeStringList:
            {
                srl = PhGetStringRef(lhs->AsString);
                srr = PhGetStringRef(rhs->AsString);
                sortResult = PhCompareStringRef(&srl, &srr, TRUE);
            }
            break;
        case PhDevicePropertyTypeBinary:
            {
                sortResult = memcmp(lhs->Binary.Buffer, rhs->Binary.Buffer, min(lhs->Binary.Size, rhs->Binary.Size));
                if (sortResult == 0)
                    sortResult = uint64cmp(lhs->Binary.Size, rhs->Binary.Size);
            }
            break;
        default:
            assert(FALSE);
        }
    }

    if (sortResult == 0)
    {
        srl = PhGetStringRef(lhsNode->DeviceItem->Properties[PhDevicePropertyName].AsString);
        srr = PhGetStringRef(rhsNode->DeviceItem->Properties[PhDevicePropertyName].AsString);
        sortResult = PhCompareStringRef(&srl, &srr, TRUE);
    }

    return PhModifySort(sortResult, DeviceTreeSortOrder);
}

VOID DeviceNodeShowProperties(
    _In_ HWND ParentWindowHandle,
    _In_ PDEVICE_NODE DeviceNode
    )
{
    PPH_DEVICE_ITEM deviceItem;

    if (DeviceNode->DeviceItem->DeviceInterface)
        deviceItem = DeviceNode->DeviceItem->Parent;
    else
        deviceItem = DeviceNode->DeviceItem;

    if (deviceItem->InstanceId)
        DeviceShowProperties(ParentWindowHandle, deviceItem);
}

VOID DeviceTreeGetSelectedDeviceItems(
    _Out_ PPH_DEVICE_ITEM** Devices,
    _Out_ PULONG NumberOfDevices
    )
{
    PH_ARRAY array;

    PhInitializeArray(&array, sizeof(PVOID), 2);

    for (ULONG i = 0; i < DeviceTree->Nodes->Count; i++)
    {
        PDEVICE_NODE node = DeviceTree->Nodes->Items[i];

        if (node->Node.Visible && node->Node.Selected)
            PhAddItemArray(&array, &node->DeviceItem);
    }

    *NumberOfDevices = (ULONG)array.Count;
    *Devices = PhFinalArrayItems(&array);
}

VOID DeviceTreeUpdateVisibleColumns(
    VOID
    )
{
    for (ULONG i = 0; i < PhMaxDeviceProperty; i++)
        DeviceTreeVisibleColumns[i] = i;

    TreeNew_GetVisibleColumnArray(
        DeviceTreeHandle,
        PhMaxDeviceProperty,
        DeviceTreeVisibleColumns
        );
}

BOOLEAN NTAPI DeviceTreeCallback(
    _In_ HWND hwnd,
    _In_ PH_TREENEW_MESSAGE Message,
    _In_ PVOID Parameter1,
    _In_ PVOID Parameter2,
    _In_ PVOID Context
    )
{
    PDEVICE_NODE node;

    switch (Message)
    {
    case TreeNewGetChildren:
        {
            PPH_TREENEW_GET_CHILDREN getChildren = Parameter1;

            if (!DeviceTree)
            {
                getChildren->Children = NULL;
                getChildren->NumberOfChildren = 0;
            }
            else
            {
                node = (PDEVICE_NODE)getChildren->Node;

                if (DeviceTreeSortOrder == NoSortOrder)
                {
                    if (!node)
                    {
                        getChildren->Children = (PPH_TREENEW_NODE*)DeviceTree->Roots->Items;
                        getChildren->NumberOfChildren = DeviceTree->Roots->Count;
                    }
                    else
                    {
                        getChildren->Children = (PPH_TREENEW_NODE*)node->Children->Items;
                        getChildren->NumberOfChildren = node->Children->Count;
                    }
                }
                else
                {
                    if (!node)
                    {
                        if (DeviceTreeSortColumn < PhMaxDeviceProperty)
                        {
                            qsort(
                                DeviceTree->Nodes->Items,
                                DeviceTree->Nodes->Count,
                                sizeof(PVOID),
                                DeviceTreeSortFunction
                                );
                        }
                    }

                    getChildren->Children = (PPH_TREENEW_NODE*)DeviceTree->Nodes->Items;
                    getChildren->NumberOfChildren = DeviceTree->Nodes->Count;
                }
            }
        }
        return TRUE;
    case TreeNewIsLeaf:
        {
            PPH_TREENEW_IS_LEAF isLeaf = Parameter1;
            node = (PDEVICE_NODE)isLeaf->Node;

            if (DeviceTreeSortOrder == NoSortOrder)
                isLeaf->IsLeaf = node->Children->Count == 0;
            else
                isLeaf->IsLeaf = TRUE;
        }
        return TRUE;
    case TreeNewGetCellText:
        {
            PPH_TREENEW_GET_CELL_TEXT getCellText = Parameter1;
            node = (PDEVICE_NODE)getCellText->Node;

            PPH_STRING text = PhGetDeviceProperty(node->DeviceItem, getCellText->Id)->AsString;

            getCellText->Text = PhGetStringRef(text);
            getCellText->Flags = TN_CACHE;
        }
        return TRUE;
    case TreeNewGetNodeColor:
        {
            PPH_TREENEW_GET_NODE_COLOR getNodeColor = Parameter1;
            node = (PDEVICE_NODE)getNodeColor->Node;

            getNodeColor->Flags = TN_CACHE | TN_AUTO_FORECOLOR;

            if (node->DeviceItem->DeviceInterface)
            {
                if (PhGetDeviceProperty(node->DeviceItem, PhDevicePropertyInterfaceEnabled)->Boolean)
                    getNodeColor->BackColor = DeviceInterfaceColor;
                else
                    getNodeColor->BackColor = DeviceDisabledInterfaceColor;
            }
            else if (node->DeviceItem->DevNodeStatus & DN_HAS_PROBLEM && (node->DeviceItem->ProblemCode != CM_PROB_DISABLED))
            {
                getNodeColor->BackColor = DeviceProblemColor;
            }
            else if (!PhGetDeviceProperty(node->DeviceItem, PhDevicePropertyIsPresent)->Boolean)
            {
                getNodeColor->BackColor = DeviceDisconnectedColor;
            }
            else if ((node->DeviceItem->Capabilities & CM_DEVCAP_HARDWAREDISABLED) || (node->DeviceItem->ProblemCode == CM_PROB_DISABLED))
            {
                getNodeColor->BackColor = DeviceDisabledColor;
            }
            else if ((HighlightUpperFiltered && node->DeviceItem->HasUpperFilters) || (HighlightLowerFiltered && node->DeviceItem->HasLowerFilters))
            {
                getNodeColor->BackColor = DeviceHighlightColor;
            }
        }
        return TRUE;
    case TreeNewGetNodeIcon:
        {
            PPH_TREENEW_GET_NODE_ICON getNodeIcon = Parameter1;

            node = (PDEVICE_NODE)getNodeIcon->Node;
            getNodeIcon->Icon = (HICON)(ULONG_PTR)node->IconIndex;
        }
        return TRUE;
    case TreeNewSortChanged:
        {
            TreeNew_GetSort(hwnd, &DeviceTreeSortColumn, &DeviceTreeSortOrder);
            TreeNew_NodesStructured(hwnd);
            if (DeviceTreeFilterSupport.FilterList)
                PhApplyTreeNewFilters(&DeviceTreeFilterSupport);
        }
        return TRUE;
    case TreeNewContextMenu:
        {
            PDEVICE_TREE activeTree;
            PPH_DEVICE_ITEM* devices;
            ULONG numberOfDevices;
            PPH_TREENEW_CONTEXT_MENU contextMenuEvent = Parameter1;
            PPH_EMENU menu;
            PPH_EMENU subMenu;
            PPH_EMENU_ITEM selectedItem;
            PPH_EMENU_ITEM autoRefresh;
            PPH_EMENU_ITEM showDisconnectedDevices;
            PPH_EMENU_ITEM showSoftwareDevices;
            PPH_EMENU_ITEM showDeviceInterfaces;
            PPH_EMENU_ITEM showDisabledDeviceInterfaces;
            PPH_EMENU_ITEM highlightUpperFiltered;
            PPH_EMENU_ITEM highlightLowerFiltered;
            PPH_EMENU_ITEM gotoServiceItem;
            PPH_EMENU_ITEM enable;
            PPH_EMENU_ITEM disable;
            PPH_EMENU_ITEM restart;
            PPH_EMENU_ITEM uninstall;
            PPH_EMENU_ITEM properties;
            BOOLEAN republish;
            BOOLEAN invalidate;

            // We muse reference the active tree here since a new tree could be
            // published on the UI thread after we show the context menu.
            activeTree = PhReferenceObject(DeviceTree);

            DeviceTreeGetSelectedDeviceItems(&devices, &numberOfDevices);

            node = (PDEVICE_NODE)contextMenuEvent->Node;

            menu = PhCreateEMenu();
            PhInsertEMenuItem(menu, PhCreateEMenuItem(0, 100, L"刷新", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, autoRefresh = PhCreateEMenuItem(0, 101, L"自动刷新", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuSeparator(), ULONG_MAX);
            PhInsertEMenuItem(menu, showDisconnectedDevices = PhCreateEMenuItem(0, 102, L"显示断开连接的设备", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, showSoftwareDevices = PhCreateEMenuItem(0, 103, L"显示软件组件", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, showDeviceInterfaces = PhCreateEMenuItem(0, 104, L"显示设备接口", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, showDisabledDeviceInterfaces = PhCreateEMenuItem(0, 105, L"显示禁用的设备接口", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, highlightUpperFiltered = PhCreateEMenuItem(0, 106, L"高亮上层过滤", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, highlightLowerFiltered = PhCreateEMenuItem(0, 107, L"高亮下层过滤", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuSeparator(), ULONG_MAX);
            PhInsertEMenuItem(menu, gotoServiceItem = PhCreateEMenuItem(0, 108, L"转到服务...", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuSeparator(), ULONG_MAX);
            PhInsertEMenuItem(menu, enable = PhCreateEMenuItem(0, 0, L"启用", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, disable = PhCreateEMenuItem(0, 1, L"禁用", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, restart = PhCreateEMenuItem(0, 2, L"重启", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, uninstall = PhCreateEMenuItem(0, 3, L"卸载", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuSeparator(), ULONG_MAX);
            subMenu = PhCreateEMenuItem(0, 0, L"打开键", NULL, NULL);
            PhInsertEMenuItem(subMenu, PhCreateEMenuItem(0, HW_KEY_INDEX_HARDWARE, L"硬件", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(subMenu, PhCreateEMenuItem(0, HW_KEY_INDEX_SOFTWARE, L"软件", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(subMenu, PhCreateEMenuItem(0, HW_KEY_INDEX_USER, L"用户", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(subMenu, PhCreateEMenuItem(0, HW_KEY_INDEX_CONFIG, L"配置", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, subMenu, ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuSeparator(), ULONG_MAX);
            PhInsertEMenuItem(menu, properties = PhCreateEMenuItem(0, 10, L"属性", NULL, NULL), ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuSeparator(), ULONG_MAX);
            PhInsertEMenuItem(menu, PhCreateEMenuItem(0, 11, L"复制", NULL, NULL), ULONG_MAX);
            PhInsertCopyCellEMenuItem(menu, 11, DeviceTreeHandle, contextMenuEvent->Column);
            PhSetFlagsEMenuItem(menu, 10, PH_EMENU_DEFAULT, PH_EMENU_DEFAULT);

            if (AutoRefreshDeviceTree)
                autoRefresh->Flags |= PH_EMENU_CHECKED;
            if (ShowDisconnected)
                showDisconnectedDevices->Flags |= PH_EMENU_CHECKED;
            if (ShowSoftwareComponents)
                showSoftwareDevices->Flags |= PH_EMENU_CHECKED;
            if (HighlightUpperFiltered)
                highlightUpperFiltered->Flags |= PH_EMENU_CHECKED;
            if (HighlightLowerFiltered)
                highlightLowerFiltered->Flags |= PH_EMENU_CHECKED;
            if (ShowDeviceInterfaces)
                showDeviceInterfaces->Flags |= PH_EMENU_CHECKED;
            if (ShowDisabledDeviceInterfaces)
                showDisabledDeviceInterfaces->Flags |= PH_EMENU_CHECKED;

            if (!node || numberOfDevices != 1)
            {
                PhSetDisabledEMenuItem(gotoServiceItem);
                PhSetDisabledEMenuItem(subMenu);
                PhSetDisabledEMenuItem(properties);
            }
            else
            {
                PPH_STRING serviceName = PhGetDeviceProperty(node->DeviceItem, PhDevicePropertyService)->AsString;
                if (PhIsNullOrEmptyString(serviceName))
                    PhSetDisabledEMenuItem(gotoServiceItem);
            }

            if (!PhGetOwnTokenAttributes().Elevated)
            {
                PhSetDisabledEMenuItem(enable);
                PhSetDisabledEMenuItem(disable);
                PhSetDisabledEMenuItem(restart);
                PhSetDisabledEMenuItem(uninstall);
            }

            selectedItem = PhShowEMenu(
                menu,
                PhMainWndHandle,
                PH_EMENU_SHOW_LEFTRIGHT,
                PH_ALIGN_LEFT | PH_ALIGN_TOP,
                contextMenuEvent->Location.x,
                contextMenuEvent->Location.y
                );

            republish = FALSE;
            invalidate = FALSE;

            if (selectedItem && selectedItem->Id != ULONG_MAX)
            {
                if (!PhHandleCopyCellEMenuItem(selectedItem))
                {
                    switch (selectedItem->Id)
                    {
                    case 0:
                    case 1:
                        {
                            for (ULONG i = 0; i < numberOfDevices; i++)
                            {
                                if (devices[i]->InstanceId)
                                    republish |= HardwareDeviceEnableDisable(hwnd, devices[i]->InstanceId, selectedItem->Id == 0);
                            }
                        }
                        break;
                    case 2:
                        {
                            for (ULONG i = 0; i < numberOfDevices; i++)
                            {
                                if (devices[i]->InstanceId)
                                    republish |= HardwareDeviceRestart(hwnd, devices[i]->InstanceId);
                            }
                        }
                        break;
                    case 3:
                        {
                            for (ULONG i = 0; i < numberOfDevices; i++)
                            {
                                if (devices[i]->InstanceId)
                                    republish |= HardwareDeviceUninstall(hwnd, devices[i]->InstanceId);
                            }
                        }
                        break;
                    case HW_KEY_INDEX_HARDWARE:
                    case HW_KEY_INDEX_SOFTWARE:
                    case HW_KEY_INDEX_USER:
                    case HW_KEY_INDEX_CONFIG:
                        if (node->DeviceItem->InstanceId)
                            HardwareDeviceOpenKey(hwnd, node->DeviceItem->InstanceId, selectedItem->Id);
                        break;
                    case 10:
                        DeviceNodeShowProperties(hwnd, node);
                        break;
                    case 11:
                        {
                            PPH_STRING text;

                            text = PhGetTreeNewText(DeviceTreeHandle, 0);
                            PhSetClipboardString(DeviceTreeHandle, &text->sr);
                            PhDereferenceObject(text);
                        }
                        break;
                    case 100:
                        republish = TRUE;
                        break;
                    case 101:
                        AutoRefreshDeviceTree = !AutoRefreshDeviceTree;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_TREE_AUTO_REFRESH, AutoRefreshDeviceTree);
                        break;
                    case 102:
                        ShowDisconnected = !ShowDisconnected;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_TREE_SHOW_DISCONNECTED, ShowDisconnected);
                        republish = TRUE;
                        break;
                    case 103:
                        ShowSoftwareComponents = !ShowSoftwareComponents;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_SHOW_SOFTWARE_COMPONENTS, ShowSoftwareComponents);
                        republish = TRUE;
                        break;
                    case 104:
                        ShowDeviceInterfaces = !ShowDeviceInterfaces;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_SHOW_DEVICE_INTERFACES, ShowDeviceInterfaces);
                        republish = TRUE;
                        break;
                    case 105:
                        ShowDisabledDeviceInterfaces = !ShowDisabledDeviceInterfaces;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_SHOW_DISABLED_DEVICE_INTERFACES, ShowDisabledDeviceInterfaces);
                        republish = TRUE;
                        break;
                    case 106:
                        HighlightUpperFiltered = !HighlightUpperFiltered;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_TREE_HIGHLIGHT_UPPER_FILTERED, HighlightUpperFiltered);
                        invalidate = TRUE;
                        break;
                    case 107:
                        HighlightLowerFiltered = !HighlightLowerFiltered;
                        PhSetIntegerSetting(SETTING_NAME_DEVICE_TREE_HIGHLIGHT_LOWER_FILTERED, HighlightLowerFiltered);
                        invalidate = TRUE;
                        break;
                    case 108:
                        {
                            PPH_STRING serviceName = PhGetDeviceProperty(node->DeviceItem, PhDevicePropertyService)->AsString;
                            PPH_SERVICE_ITEM serviceItem;

                            if (!PhIsNullOrEmptyString(serviceName))
                            {
                                if (serviceItem = PhReferenceServiceItem(PhGetString(serviceName)))
                                {
                                    ProcessHacker_SelectTabPage(1);
                                    ProcessHacker_SelectServiceItem(serviceItem);
                                    PhDereferenceObject(serviceItem);
                                }
                            }
                        }
                        break;
                    }
                }
            }

            PhDestroyEMenu(menu);

            if (republish)
            {
                DeviceTreePublishAsync(TRUE);
            }
            else if (invalidate)
            {
                InvalidateDeviceNodes();
                if (DeviceTreeFilterSupport.FilterList)
                    PhApplyTreeNewFilters(&DeviceTreeFilterSupport);
            }

            PhFree(devices);
            PhDereferenceObject(activeTree);
        }
        return TRUE;
    case TreeNewLeftDoubleClick:
        {
            PPH_TREENEW_MOUSE_EVENT mouseEvent = Parameter1;
            node = (PDEVICE_NODE)mouseEvent->Node;

            if (node)
                DeviceNodeShowProperties(hwnd, node);
        }
        return TRUE;
    case TreeNewHeaderRightClick:
        {
            PH_TN_COLUMN_MENU_DATA data;

            data.TreeNewHandle = hwnd;
            data.MouseEvent = Parameter1;
            data.DefaultSortColumn = 0;
            data.DefaultSortOrder = NoSortOrder;
            PhInitializeTreeNewColumnMenuEx(&data, PH_TN_COLUMN_MENU_SHOW_RESET_SORT);

            data.Selection = PhShowEMenu(
                data.Menu,
                hwnd,
                PH_EMENU_SHOW_LEFTRIGHT,
                PH_ALIGN_LEFT | PH_ALIGN_TOP,
                data.MouseEvent->ScreenLocation.x,
                data.MouseEvent->ScreenLocation.y
                );
            PhHandleTreeNewColumnMenu(&data);
            PhDeleteTreeNewColumnMenu(&data);
            DeviceTreeUpdateVisibleColumns();
        }
        return TRUE;
    }

    return FALSE;
}

VOID DevicesTreeLoadSettings(
    _In_ HWND TreeNewHandle
    )
{
    PPH_STRING settings;
    PH_INTEGER_PAIR sortSettings;

    settings = PhGetStringSetting(SETTING_NAME_DEVICE_TREE_COLUMNS);
    sortSettings = PhGetIntegerPairSetting(SETTING_NAME_DEVICE_TREE_SORT);
    PhCmLoadSettings(TreeNewHandle, &settings->sr);
    TreeNew_SetSort(TreeNewHandle, (ULONG)sortSettings.X, (ULONG)sortSettings.Y);
    PhDereferenceObject(settings);
}

VOID DevicesTreeSaveSettings(
    VOID
    )
{
    PPH_STRING settings;
    PH_INTEGER_PAIR sortSettings;
    ULONG sortColumn;
    ULONG sortOrder;

    if (!DeviceTabCreated)
        return;

    settings = PhCmSaveSettings(DeviceTreeHandle);
    TreeNew_GetSort(DeviceTreeHandle, &sortColumn, &sortOrder);
    sortSettings.X = sortColumn;
    sortSettings.Y = sortOrder;
    PhSetStringSetting2(SETTING_NAME_DEVICE_TREE_COLUMNS, &settings->sr);
    PhSetIntegerPairSetting(SETTING_NAME_DEVICE_TREE_SORT, sortSettings);
    PhDereferenceObject(settings);
}

VOID DevicesTreeImageListInitialize(
    _In_ HWND TreeNewHandle
    )
{
    LONG dpi;

    dpi = PhGetWindowDpi(TreeNewHandle);
    DeviceIconSize.X = PhGetSystemMetrics(SM_CXSMICON, dpi);
    DeviceIconSize.Y = PhGetSystemMetrics(SM_CYSMICON, dpi);

    if (DeviceImageList)
    {
        PhImageListSetIconSize(DeviceImageList, DeviceIconSize.X, DeviceIconSize.Y);
    }
    else
    {
        DeviceImageList = PhImageListCreate(
            DeviceIconSize.X,
            DeviceIconSize.Y,
            ILC_MASK | ILC_COLOR32,
            200,
            100
            );
    }

    PhImageListAddIcon(DeviceImageList, PhGetApplicationIcon(TRUE));

    TreeNew_SetImageList(DeviceTreeHandle, DeviceImageList);
}

const DEVICE_PROPERTY_TABLE_ENTRY DeviceItemPropertyTable[] =
{
    { PhDevicePropertyName, L"名称", TRUE, 400, 0 },
    { PhDevicePropertyManufacturer, L"制造商", TRUE, 180, 0 },
    { PhDevicePropertyService, L"服务", TRUE, 120, 0 },
    { PhDevicePropertyClass, L"类", TRUE, 120, 0 },
    { PhDevicePropertyEnumeratorName, L"枚举器", TRUE, 80, 0 },
    { PhDevicePropertyInstallDate, L"已安装", TRUE, 160, 0 },

    { PhDevicePropertyFirstInstallDate, L"首次安装", FALSE, 160, 0 },
    { PhDevicePropertyLastArrivalDate, L"上次连接", FALSE, 160, 0 },
    { PhDevicePropertyLastRemovalDate, L"上次移除", FALSE, 160, 0 },
    { PhDevicePropertyDeviceDesc, L"描述", FALSE, 280, 0 },
    { PhDevicePropertyFriendlyName, L"友好名称", FALSE, 220, 0 },
    { PhDevicePropertyInstanceId, L"实例ID", FALSE, 240, DT_PATH_ELLIPSIS },
    { PhDevicePropertyParentInstanceId, L"父实例ID", FALSE, 240, DT_PATH_ELLIPSIS },
    { PhDevicePropertyPDOName, L"PDO名称", FALSE, 180, DT_PATH_ELLIPSIS },
    { PhDevicePropertyLocationInfo, L"位置信息", FALSE, 180, DT_PATH_ELLIPSIS },
    { PhDevicePropertyClassGuid, L"类GUID", FALSE, 80, 0 },
    { PhDevicePropertyDriver, L"驱动程序", FALSE, 180, DT_PATH_ELLIPSIS },
    { PhDevicePropertyDriverVersion, L"驱动版本", FALSE, 80, 0 },
    { PhDevicePropertyDriverDate, L"驱动日期", FALSE, 80, 0 },
    { PhDevicePropertyFirmwareDate, L"固件日期", FALSE, 80, 0 },
    { PhDevicePropertyFirmwareVersion, L"固件版本", FALSE, 80, 0 },
    { PhDevicePropertyFirmwareRevision, L"固件修订", FALSE, 80, 0 },
    { PhDevicePropertyHasProblem, L"存在问题", FALSE, 80, 0 },
    { PhDevicePropertyProblemCode, L"问题代码", FALSE, 80, 0 },
    { PhDevicePropertyProblemStatus, L"问题状态", FALSE, 80, 0 },
    { PhDevicePropertyDevNodeStatus, L"节点状态标记", FALSE, 80, 0 },
    { PhDevicePropertyDevCapabilities, L"能力", FALSE, 80, 0 },
    { PhDevicePropertyUpperFilters, L"上层过滤器", FALSE, 80, 0 },
    { PhDevicePropertyLowerFilters, L"下层过滤器", FALSE, 80, 0 },
    { PhDevicePropertyHardwareIds, L"硬件 IDs ", FALSE, 80, 0 },
    { PhDevicePropertyCompatibleIds, L"兼容ID", FALSE, 80, 0 },
    { PhDevicePropertyConfigFlags, L"配置标记", FALSE, 80, 0 },
    { PhDevicePropertyUINumber, L"编号", FALSE, 80, 0 },
    { PhDevicePropertyBusTypeGuid, L"总线类型GUID", FALSE, 80, 0 },
    { PhDevicePropertyLegacyBusType, L"传统总线类型", FALSE, 80, 0 },
    { PhDevicePropertyBusNumber, L"总线编号", FALSE, 80, 0 },
    { PhDevicePropertySecurity, L"安全描述符（二进制）", FALSE, 80, 0 },
    { PhDevicePropertySecuritySDS, L"安全描述符", FALSE, 80, 0 },
    { PhDevicePropertyDevType, L"类型", FALSE, 80, 0 },
    { PhDevicePropertyExclusive, L"独占", FALSE, 80, 0 },
    { PhDevicePropertyCharacteristics, L"特性", FALSE, 80, 0 },
    { PhDevicePropertyAddress, L"地址", FALSE, 80, 0 },
    { PhDevicePropertyPowerData, L"电源数据", FALSE, 80, 0 },
    { PhDevicePropertyRemovalPolicy, L"移除策略", FALSE, 80, 0 },
    { PhDevicePropertyRemovalPolicyDefault, L"默认移除策略", FALSE, 80, 0 },
    { PhDevicePropertyRemovalPolicyOverride, L"替代移除策略", FALSE, 80, 0 },
    { PhDevicePropertyInstallState, L"安装状态", FALSE, 80, 0 },
    { PhDevicePropertyLocationPaths, L"位置路径", FALSE, 80, 0 },
    { PhDevicePropertyBaseContainerId, L"基础容器ID", FALSE, 80, 0 },
    { PhDevicePropertyEjectionRelations, L"弹出关系", FALSE, 80, 0 },
    { PhDevicePropertyRemovalRelations, L"移除关系", FALSE, 80, 0 },
    { PhDevicePropertyPowerRelations, L"电源关系", FALSE, 80, 0 },
    { PhDevicePropertyBusRelations, L"总线关系", FALSE, 80, 0 },
    { PhDevicePropertyChildren, L"子", FALSE, 80, 0 },
    { PhDevicePropertySiblings, L"同级", FALSE, 80, 0 },
    { PhDevicePropertyTransportRelations, L"传输关系", FALSE, 80, 0 },
    { PhDevicePropertyReported, L"已报告", FALSE, 80, 0 },
    { PhDevicePropertyLegacy, L"传统", FALSE, 80, 0 },
    { PhDevicePropertyContainerId, L"容器ID", FALSE, 80, 0 },
    { PhDevicePropertyInLocalMachineContainer, L"本地机器容器", FALSE, 80, 0 },
    { PhDevicePropertyModel, L"型号", FALSE, 80, 0 },
    { PhDevicePropertyModelId, L"型号ID", FALSE, 80, 0 },
    { PhDevicePropertyFriendlyNameAttributes, L"友好名称属性", FALSE, 80, 0 },
    { PhDevicePropertyManufacturerAttributes, L"制造属性", FALSE, 80, 0 },
    { PhDevicePropertyPresenceNotForDevice, L"非设备的标识", FALSE, 80, 0 },
    { PhDevicePropertySignalStrength, L"信号强度", FALSE, 80, 0 },
    { PhDevicePropertyIsAssociateableByUserAction, L"可通过用户操作关联", FALSE, 80, 0 },
    { PhDevicePropertyShowInUninstallUI, L"显示卸载界面", FALSE, 80, 0 },
    { PhDevicePropertyNumaProximityDomain, L"NUMA邻近性默认", FALSE, 80, 0 },
    { PhDevicePropertyDHPRebalancePolicy, L"DHP重新平衡政策", FALSE, 80, 0 },
    { PhDevicePropertyNumaNode, L"Numa节点", FALSE, 80, 0 },
    { PhDevicePropertyBusReportedDeviceDesc, L"总线报告描述", FALSE, 80, 0 },
    { PhDevicePropertyIsPresent, L"当前", FALSE, 80, 0 },
    { PhDevicePropertyConfigurationId, L"配置ID", FALSE, 80, 0 },
    { PhDevicePropertyReportedDeviceIdsHash, L"报告ID哈希", FALSE, 80, 0 },
    { PhDevicePropertyPhysicalDeviceLocation, L"物理位置", FALSE, 80, 0 },
    { PhDevicePropertyBiosDeviceName, L"BIOS名称", FALSE, 80, 0 },
    { PhDevicePropertyDriverProblemDesc, L"问题描述", FALSE, 80, 0 },
    { PhDevicePropertyDebuggerSafe, L"调试器安全", FALSE, 80, 0 },
    { PhDevicePropertyPostInstallInProgress, L"后安装进行中", FALSE, 80, 0 },
    { PhDevicePropertyStack, L"堆栈", FALSE, 80, 0 },
    { PhDevicePropertyExtendedConfigurationIds, L"扩展配置ID", FALSE, 80, 0 },
    { PhDevicePropertyIsRebootRequired, L"需要重启", FALSE, 80, 0 },
    { PhDevicePropertyDependencyProviders, L"依赖提供者", FALSE, 80, 0 },
    { PhDevicePropertyDependencyDependents, L"依赖项", FALSE, 80, 0 },
    { PhDevicePropertySoftRestartSupported, L"支持软重启", FALSE, 80, 0 },
    { PhDevicePropertyExtendedAddress, L"扩展地址", FALSE, 80, 0 },
    { PhDevicePropertyAssignedToGuest, L"分配给虚拟机", FALSE, 80, 0 },
    { PhDevicePropertyCreatorProcessId, L"创建者进程ID", FALSE, 80, 0 },
    { PhDevicePropertyFirmwareVendor, L"固件供应商", FALSE, 80, 0 },
    { PhDevicePropertySessionId, L"会话ID", FALSE, 80, 0 },
    { PhDevicePropertyDriverDesc, L"驱动程序描述", FALSE, 80, 0 },
    { PhDevicePropertyDriverInfPath, L"驱动INF路径", FALSE, 80, 0 },
    { PhDevicePropertyDriverInfSection, L"驱动INF节", FALSE, 80, 0 },
    { PhDevicePropertyDriverInfSectionExt, L"驱动INF节扩展", FALSE, 80, 0 },
    { PhDevicePropertyMatchingDeviceId, L"匹配ID", FALSE, 80, 0 },
    { PhDevicePropertyDriverProvider, L"驱动提供者", FALSE, 80, 0 },
    { PhDevicePropertyDriverPropPageProvider, L"驱动程序属性页提供者", FALSE, 80, 0 },
    { PhDevicePropertyDriverCoInstallers, L"驱动共同安装者", FALSE, 80, 0 },
    { PhDevicePropertyResourcePickerTags, L"资源选择器标签", FALSE, 80, 0 },
    { PhDevicePropertyResourcePickerExceptions, L"资源选择器例外", FALSE, 80, 0 },
    { PhDevicePropertyDriverRank, L"驱动排名", FALSE, 80, 0 },
    { PhDevicePropertyDriverLogoLevel, L"驱动LOGO级别", FALSE, 80, 0 },
    { PhDevicePropertyNoConnectSound, L"无连接声音", FALSE, 80, 0 },
    { PhDevicePropertyGenericDriverInstalled, L"已安装通用驱动", FALSE, 80, 0 },
    { PhDevicePropertyAdditionalSoftwareRequested, L"请求额外软件", FALSE, 80, 0 },
    { PhDevicePropertySafeRemovalRequired, L"需要安全移除", FALSE, 80, 0 },
    { PhDevicePropertySafeRemovalRequiredOverride, L"覆盖需要保存移除", FALSE, 80, 0 },

    { PhDevicePropertyPkgModel, L"包模型", FALSE, 80, 0 },
    { PhDevicePropertyPkgVendorWebSite, L"包供应商网站", FALSE, 80, 0 },
    { PhDevicePropertyPkgDetailedDescription, L"包描述", FALSE, 80, 0 },
    { PhDevicePropertyPkgDocumentationLink, L"包文档", FALSE, 80, 0 },
    { PhDevicePropertyPkgIcon, L"包图标", FALSE, 80, 0 },
    { PhDevicePropertyPkgBrandingIcon, L"包品牌图标", FALSE, 80, 0 },

    { PhDevicePropertyClassUpperFilters, L"类上层过滤器", FALSE, 80, 0 },
    { PhDevicePropertyClassLowerFilters, L"类下层过滤器", FALSE, 80, 0 },
    { PhDevicePropertyClassSecurity, L"类安全描述符（二进制）", FALSE, 80, 0 },
    { PhDevicePropertyClassSecuritySDS, L"类安全描述符", FALSE, 80, 0 },
    { PhDevicePropertyClassDevType, L"类类型", FALSE, 80, 0 },
    { PhDevicePropertyClassExclusive, L"类独占", FALSE, 80, 0 },
    { PhDevicePropertyClassCharacteristics, L"类特性", FALSE, 80, 0 },
    { PhDevicePropertyClassName, L"类设备名称", FALSE, 80, 0 },
    { PhDevicePropertyClassClassName, L"类名", FALSE, 80, 0 },
    { PhDevicePropertyClassIcon, L"类图标", FALSE, 80, 0 },
    { PhDevicePropertyClassClassInstaller, L"类安装程序", FALSE, 80, 0 },
    { PhDevicePropertyClassPropPageProvider, L"类属性页提供者", FALSE, 80, 0 },
    { PhDevicePropertyClassNoInstallClass, L"类不安装", FALSE, 80, 0 },
    { PhDevicePropertyClassNoDisplayClass, L"类不显示", FALSE, 80, 0 },
    { PhDevicePropertyClassSilentInstall, L"类静默安装", FALSE, 80, 0 },
    { PhDevicePropertyClassNoUseClass, L"类无用类", FALSE, 80, 0 },
    { PhDevicePropertyClassDefaultService, L"类默认服务", FALSE, 80, 0 },
    { PhDevicePropertyClassIconPath, L"类图标路径", FALSE, 80, 0 },
    { PhDevicePropertyClassDHPRebalanceOptOut, L"类DHP重新平衡选择退出", FALSE, 80, 0 },
    { PhDevicePropertyClassClassCoInstallers, L"类共同安装者", FALSE, 80, 0 },

    { PhDevicePropertyInterfaceFriendlyName, L"接口友好名称", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceEnabled, L"接口启用", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceClassGuid, L"接口类GUID", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceReferenceString, L"接口参考", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceRestricted, L"接口受限", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceUnrestrictedAppCapabilities, L"接口不受限制的应用能力", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceSchematicName, L"接口示意名称", FALSE, 80, 0 },

    { PhDevicePropertyInterfaceClassDefaultInterface, L"接口类默认接口", FALSE, 80, 0 },
    { PhDevicePropertyInterfaceClassName, L"接口类名称", FALSE, 80, 0 },

    { PhDevicePropertyContainerAddress, L"容器地址", FALSE, 80, 0 },
    { PhDevicePropertyContainerDiscoveryMethod, L"容器发现方法", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsEncrypted, L"容器已加密", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsAuthenticated, L"容器已认证", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsConnected, L"容器已连接", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsPaired, L"容器已配对", FALSE, 80, 0 },
    { PhDevicePropertyContainerIcon, L"容器图标", FALSE, 80, 0 },
    { PhDevicePropertyContainerVersion, L"容器版本", FALSE, 80, 0 },
    { PhDevicePropertyContainerLastSeen, L"容器最后一次看到", FALSE, 80, 0 },
    { PhDevicePropertyContainerLastConnected, L"容器最后一次连接", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsShowInDisconnectedState, L"容器在断开状态下显示", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsLocalMachine, L"容器本地机器", FALSE, 80, 0 },
    { PhDevicePropertyContainerMetadataPath, L"容器元数据路径", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsMetadataSearchInProgress, L"容器元数据搜索进行中", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsMetadataChecksum, L"元数据校验和", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsNotInterestingForDisplay, L"容器不适合显示", FALSE, 80, 0 },
    { PhDevicePropertyContainerLaunchDeviceStageOnDeviceConnect, L"容器连接时启动", FALSE, 80, 0 },
    { PhDevicePropertyContainerLaunchDeviceStageFromExplorer, L"容器从资源管理器启动", FALSE, 80, 0 },
    { PhDevicePropertyContainerBaselineExperienceId, L"容器基线体验ID", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsDeviceUniquelyIdentifiable, L"容器唯一识别", FALSE, 80, 0 },
    { PhDevicePropertyContainerAssociationArray, L"容器关联", FALSE, 80, 0 },
    { PhDevicePropertyContainerDeviceDescription1, L"容器描述", FALSE, 80, 0 },
    { PhDevicePropertyContainerDeviceDescription2, L"容器其他描述", FALSE, 80, 0 },
    { PhDevicePropertyContainerHasProblem, L"容器存在问题", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsSharedDevice, L"容器共享设备", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsNetworkDevice, L"容器网络设备", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsDefaultDevice, L"容器默认设备", FALSE, 80, 0 },
    { PhDevicePropertyContainerMetadataCabinet, L"容器元数据柜", FALSE, 80, 0 },
    { PhDevicePropertyContainerRequiresPairingElevation, L"容器需要配对权限提升", FALSE, 80, 0 },
    { PhDevicePropertyContainerExperienceId, L"容器体验ID", FALSE, 80, 0 },
    { PhDevicePropertyContainerCategory, L"容器类别", FALSE, 80, 0 },
    { PhDevicePropertyContainerCategoryDescSingular, L"容器类别描述", FALSE, 80, 0 },
    { PhDevicePropertyContainerCategoryDescPlural, L"容器类别描述（复数）", FALSE, 80, 0 },
    { PhDevicePropertyContainerCategoryIcon, L"容器类别图标", FALSE, 80, 0 },
    { PhDevicePropertyContainerCategoryGroupDesc, L"容器类别组描述", FALSE, 80, 0 },
    { PhDevicePropertyContainerCategoryGroupIcon, L"容器类别组图标", FALSE, 80, 0 },
    { PhDevicePropertyContainerPrimaryCategory, L"容器主要类别", FALSE, 80, 0 },
    { PhDevicePropertyContainerUnpairUninstall, L"容器取消配对卸载", FALSE, 80, 0 },
    { PhDevicePropertyContainerRequiresUninstallElevation, L"容器需要卸载权限提升", FALSE, 80, 0 },
    { PhDevicePropertyContainerDeviceFunctionSubRank, L"容器功能子级排名", FALSE, 80, 0 },
    { PhDevicePropertyContainerAlwaysShowDeviceAsConnected, L"容器始终显示连接", FALSE, 80, 0 },
    { PhDevicePropertyContainerConfigFlags, L"容器控制标志", FALSE, 80, 0 },
    { PhDevicePropertyContainerPrivilegedPackageFamilyNames, L"容器特权包家族名称", FALSE, 80, 0 },
    { PhDevicePropertyContainerCustomPrivilegedPackageFamilyNames, L"容器自定义特权包家族名称", FALSE, 80, 0 },
    { PhDevicePropertyContainerIsRebootRequired, L"容器需要重启", FALSE, 80, 0 },
    { PhDevicePropertyContainerFriendlyName, L"容器友好名称", FALSE, 80, 0 },
    { PhDevicePropertyContainerManufacturer, L"容器制造", FALSE, 80, 0 },
    { PhDevicePropertyContainerModelName, L"容器型号名称", FALSE, 80, 0 },
    { PhDevicePropertyContainerModelNumber, L"容器型号编号", FALSE, 80, 0 },
    { PhDevicePropertyContainerInstallInProgress, L"容器正在安装中", FALSE, 80, 0 },

    { PhDevicePropertyObjectType, L"对象类型", FALSE, 80, 0 },

    { PhDevicePropertyPciInterruptSupport, L"PCI中断支持", FALSE, 80, 0 },
    { PhDevicePropertyPciExpressCapabilityControl, L"PCI Express能力控制", FALSE, 80, 0 },
    { PhDevicePropertyPciNativeExpressControl, L"PCI原生Express控制", FALSE, 80, 0 },
    { PhDevicePropertyPciSystemMsiSupport, L"PCI系统MSI支持", FALSE, 80, 0 },

    { PhDevicePropertyStoragePortable, L"存储便携", FALSE, 80, 0 },
    { PhDevicePropertyStorageRemovableMedia, L"存储可移动介质", FALSE, 80, 0 },
    { PhDevicePropertyStorageSystemCritical, L"存储系统关键  ", FALSE, 80, 0 },
    { PhDevicePropertyStorageDiskNumber, L"存储磁盘号  ", FALSE, 80, 0 },
    { PhDevicePropertyStoragePartitionNumber, L"存储磁盘分区号  ", FALSE, 80, 0 },

    { PhDevicePropertyGpuLuid, L" GPU LUID  ", FALSE, 80, 0 },
    { PhDevicePropertyGpuPhysicalAdapterIndex, L"GPU物理适配器索引  ", FALSE, 80, 0 },
};
C_ASSERT(RTL_NUMBER_OF(DeviceItemPropertyTable) == PhMaxDeviceProperty);
const ULONG DeviceItemPropertyTableCount = RTL_NUMBER_OF(DeviceItemPropertyTable);

VOID DevicesTreeInitialize(
    _In_ HWND TreeNewHandle
    )
{
    ULONG count = 0;

    DeviceTreeHandle = TreeNewHandle;

    PhSetControlTheme(DeviceTreeHandle, L"explorer");
    TreeNew_SetCallback(DeviceTreeHandle, DeviceTreeCallback, NULL);
    TreeNew_SetExtendedFlags(DeviceTreeHandle, TN_FLAG_ITEM_DRAG_SELECT, TN_FLAG_ITEM_DRAG_SELECT);
    SendMessage(TreeNew_GetTooltips(DeviceTreeHandle), TTM_SETDELAYTIME, TTDT_AUTOPOP, MAXSHORT);

    DevicesTreeImageListInitialize(DeviceTreeHandle);

    TreeNew_SetRedraw(DeviceTreeHandle, FALSE);

    for (ULONG i = 0; i < DeviceItemPropertyTableCount; i++)
    {
        ULONG displayIndex;
        const DEVICE_PROPERTY_TABLE_ENTRY* entry;

        entry = &DeviceItemPropertyTable[i];

        assert(i == entry->PropClass);

        if (entry->PropClass == PhDevicePropertyName)
        {
            assert(i == 0);
            displayIndex = -2;
        }
        else
        {
            assert(i > 0);
            displayIndex = i - 1;
        }

        PhAddTreeNewColumn(
            DeviceTreeHandle,
            entry->PropClass,
            entry->ColumnVisible,
            entry->ColumnName,
            entry->ColumnWidth,
            PH_ALIGN_LEFT,
            displayIndex,
            entry->ColumnTextFlags
            );
    }

    DevicesTreeLoadSettings(DeviceTreeHandle);

    TreeNew_SetRedraw(DeviceTreeHandle, TRUE);

    TreeNew_SetTriState(DeviceTreeHandle, TRUE);

    DeviceTreeUpdateVisibleColumns();

    if (PhGetIntegerSetting(L"TreeListCustomRowSize"))
    {
        ULONG treelistCustomRowSize = PhGetIntegerSetting(L"TreeListCustomRowSize");

        if (treelistCustomRowSize < 15)
            treelistCustomRowSize = 15;

        TreeNew_SetRowHeight(DeviceTreeHandle, treelistCustomRowSize);
    }

    PhInitializeTreeNewFilterSupport(&DeviceTreeFilterSupport, DeviceTreeHandle, &DeviceFilterList);
    if (ToolStatusInterface)
    {
        PhRegisterCallback(
            ToolStatusInterface->SearchChangedEvent,
            DeviceTreeSearchChangedHandler,
            NULL,
            &SearchChangedRegistration);
        PhAddTreeNewFilter(&DeviceTreeFilterSupport, DeviceTreeFilterCallback, NULL);
    }

    if (PhGetIntegerSetting(L"EnableThemeSupport"))
    {
        PhInitializeWindowTheme(DeviceTreeHandle, TRUE);
        TreeNew_ThemeSupport(DeviceTreeHandle, TRUE);
    }
}

BOOLEAN DevicesTabPageCallback(
    _In_ struct _PH_MAIN_TAB_PAGE* Page,
    _In_ PH_MAIN_TAB_PAGE_MESSAGE Message,
    _In_opt_ PVOID Parameter1,
    _In_opt_ PVOID Parameter2
    )
{
    switch (Message)
    {
    case MainTabPageCreateWindow:
        {
            HWND hwnd;
            ULONG thinRows;
            ULONG treelistBorder;
            ULONG treelistCustomColors;
            PH_TREENEW_CREATEPARAMS treelistCreateParams = { 0 };

            thinRows = PhGetIntegerSetting(L"ThinRows") ? TN_STYLE_THIN_ROWS : 0;
            treelistBorder = (PhGetIntegerSetting(L"TreeListBorderEnable") && !PhGetIntegerSetting(L"EnableThemeSupport")) ? WS_BORDER : 0;
            treelistCustomColors = PhGetIntegerSetting(L"TreeListCustomColorsEnable") ? TN_STYLE_CUSTOM_COLORS : 0;

            if (treelistCustomColors)
            {
                treelistCreateParams.TextColor = PhGetIntegerSetting(L"TreeListCustomColorText");
                treelistCreateParams.FocusColor = PhGetIntegerSetting(L"TreeListCustomColorFocus");
                treelistCreateParams.SelectionColor = PhGetIntegerSetting(L"TreeListCustomColorSelection");
            }

            hwnd = CreateWindow(
                PH_TREENEW_CLASSNAME,
                NULL,
                WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS | TN_STYLE_ICONS | TN_STYLE_DOUBLE_BUFFERED | TN_STYLE_ANIMATE_DIVIDER | thinRows | treelistBorder | treelistCustomColors,
                0,
                0,
                3,
                3,
                Parameter2,
                NULL,
                PluginInstance->DllBase,
                &treelistCreateParams
                );

            if (!hwnd)
                return FALSE;

            DeviceTabCreated = TRUE;

            DevicesTreeInitialize(hwnd);

            if (Parameter1)
            {
                *(HWND*)Parameter1 = hwnd;
            }
        }
        return TRUE;
    case MainTabPageLoadSettings:
        {
            NOTHING;
        }
        return TRUE;
    case MainTabPageSaveSettings:
        {
            DevicesTreeSaveSettings();
        }
        return TRUE;
    case MainTabPageSelected:
        {
            DeviceTabSelected = (BOOLEAN)Parameter1;
            if (DeviceTabSelected)
                DeviceTreePublishAsync(FALSE);
        }
        break;
    case MainTabPageFontChanged:
        {
            HFONT font = (HFONT)Parameter1;

            if (DeviceTreeHandle)
                SendMessage(DeviceTreeHandle, WM_SETFONT, (WPARAM)Parameter1, TRUE);
        }
        break;
    case MainTabPageDpiChanged:
        {
            if (DeviceImageList)
            {
                DevicesTreeImageListInitialize(DeviceTreeHandle);

                if (DeviceTree)
                {
                    for (ULONG i = 0; i < DeviceTree->Nodes->Count; i++)
                    {
                        PDEVICE_NODE node = DeviceTree->Nodes->Items[i];
                        HICON iconHandle = PhGetDeviceIcon(node->DeviceItem, &DeviceIconSize);
                        if (iconHandle)
                        {
                            node->IconIndex = PhImageListAddIcon(DeviceImageList, iconHandle);
                            DestroyIcon(iconHandle);
                        }
                        else
                        {
                            node->IconIndex = 0; // Must be reset (dmex)
                        }
                    }
                }
            }
        }
        break;
    }

    return FALSE;
}

VOID NTAPI ToolStatusActivateContent(
    _In_ BOOLEAN Select
    )
{
    SetFocus(DeviceTreeHandle);

    if (Select)
    {
        if (TreeNew_GetFlatNodeCount(DeviceTreeHandle) > 0)
        {
            PDEVICE_NODE node;

            TreeNew_DeselectRange(DeviceTreeHandle, 0, -1);

            node = (PDEVICE_NODE)TreeNew_GetFlatNode(DeviceTreeHandle, 0);

            if (!node->Node.Visible)
            {
                TreeNew_SetFocusNode(DeviceTreeHandle, &node->Node);
                TreeNew_SetMarkNode(DeviceTreeHandle, &node->Node);
                TreeNew_SelectRange(DeviceTreeHandle, node->Node.Index, node->Node.Index);
                TreeNew_EnsureVisible(DeviceTreeHandle, &node->Node);
            }
        }
    }
}

HWND NTAPI ToolStatusGetTreeNewHandle(
    VOID
    )
{
    return DeviceTreeHandle;
}

VOID NTAPI DeviceProviderCallbackHandler(
    _In_opt_ PVOID Parameter,
    _In_opt_ PVOID Context
    )
{
    if (DeviceTabCreated && DeviceTabSelected && AutoRefreshDeviceTree)
        ProcessHacker_Invoke(DeviceTreePublish, DeviceTreeCreateIfNecessary(FALSE));
}

VOID DeviceTreeRemoveDeviceNode(
    _In_ PDEVICE_NODE Node,
    _In_opt_ PVOID Context
    )
{
    NOTHING;
}

VOID NTAPI DeviceTreeProcessesUpdatedCallback(
    _In_opt_ PVOID Parameter,
    _In_opt_ PVOID Context
    )
{
    if (!DeviceTreeHandle)
        return;

    // piggy back off the processes update callback to handle state changes
    PH_TICK_SH_STATE_TN(
        DEVICE_NODE,
        ShState,
        DeviceNodeStateList,
        DeviceTreeRemoveDeviceNode,
        DeviceHighlightingDuration,
        DeviceTreeHandle,
        TRUE,
        NULL,
        NULL
        );
}

VOID DeviceTreeUpdateCachedSettings(
    _In_ BOOLEAN UpdateColors
    )
{
    AutoRefreshDeviceTree = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_TREE_AUTO_REFRESH);
    ShowDisconnected = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_TREE_SHOW_DISCONNECTED);
    ShowSoftwareComponents = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_SHOW_SOFTWARE_COMPONENTS);
    ShowDeviceInterfaces = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_SHOW_DEVICE_INTERFACES);
    ShowDisabledDeviceInterfaces = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_SHOW_DISABLED_DEVICE_INTERFACES);
    HighlightUpperFiltered = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_TREE_HIGHLIGHT_UPPER_FILTERED);
    HighlightLowerFiltered = !!PhGetIntegerSetting(SETTING_NAME_DEVICE_TREE_HIGHLIGHT_LOWER_FILTERED);
    DeviceHighlightingDuration = PhGetIntegerSetting(SETTING_NAME_DEVICE_HIGHLIGHTING_DURATION);

    if (UpdateColors)
    {
        DeviceProblemColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_PROBLEM_COLOR);
        DeviceDisabledColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_DISABLED_COLOR);
        DeviceDisconnectedColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_DISCONNECTED_COLOR);
        DeviceHighlightColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_HIGHLIGHT_COLOR);
        DeviceInterfaceColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_INTERFACE_COLOR);
        DeviceDisabledInterfaceColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_DISABLED_INTERFACE_COLOR);
        DeviceArrivedColor = PhGetIntegerSetting(SETTING_NAME_DEVICE_ARRIVED_COLOR);
    }
}

VOID NTAPI DeviceTreeSettingsUpdatedCallback(
    _In_opt_ PVOID Parameter,
    _In_opt_ PVOID Context
    )
{
    DeviceTreeUpdateCachedSettings(FALSE);
}

VOID InitializeDevicesTab(
    VOID
    )
{
    PH_MAIN_TAB_PAGE page;

    DeviceTreeType = PhCreateObjectType(L"DevicesTree", 0, DeviceTreeDeleteProcedure);

    PhRegisterCallback(
        PhGetGeneralCallback(GeneralCallbackDeviceNotificationEvent),
        DeviceProviderCallbackHandler,
        NULL,
        &DeviceNotifyRegistration
        );
    PhRegisterCallback(
        PhGetGeneralCallback(GeneralCallbackProcessesUpdated),
        DeviceTreeProcessesUpdatedCallback,
        NULL,
        &ProcessesUpdatedCallbackRegistration
        );
    PhRegisterCallback(
        PhGetGeneralCallback(GeneralCallbackSettingsUpdated),
        DeviceTreeSettingsUpdatedCallback,
        NULL,
        &SettingsUpdatedCallbackRegistration
        );

    DeviceTreeUpdateCachedSettings(TRUE);

    RtlZeroMemory(&page, sizeof(PH_MAIN_TAB_PAGE));
    PhInitializeStringRef(&page.Name, L"设备");
    page.Callback = DevicesTabPageCallback;
    DevicesAddedTabPage = PhPluginCreateTabPage(&page);

    if (ToolStatusInterface = PhGetPluginInterfaceZ(TOOLSTATUS_PLUGIN_NAME, TOOLSTATUS_INTERFACE_VERSION))
    {
        PTOOLSTATUS_TAB_INFO tabInfo;

        tabInfo = ToolStatusInterface->RegisterTabInfo(DevicesAddedTabPage->Index);
        tabInfo->BannerText = L"搜索设备";
        tabInfo->ActivateContent = ToolStatusActivateContent;
        tabInfo->GetTreeNewHandle = ToolStatusGetTreeNewHandle;
    }
}
